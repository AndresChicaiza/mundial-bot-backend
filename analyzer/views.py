import json
import time
from collections import defaultdict

from groq import Groq
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

SYSTEM_PROMPT = (
    "Eres ScoutBot, analista del Mundial 2026. "
    "Busca en internet datos reales y responde SOLO con JSON válido sin markdown. "
    "IMPORTANTE: Todas las probabilidades y porcentajes deben ser números enteros del 0 al 100 (ej: 45, no 0.45). "
    "El JSON debe tener: partido (equipo_local, equipo_visitante, fecha, estadio, fase), "
    "probabilidades_resultado (victoria_local, empate, victoria_visitante, descripcion), "
    "goles (total_esperado, local_esperado, visitante_esperado, ambos_anotan_prob, mas_de_2_5_prob, "
    "goleadores_probables con nombre/equipo/probabilidad/razon), "
    "tarjetas (amarillas_esperadas, local_amarillas, visitante_amarillas, rojas_prob, "
    "jugadores_en_riesgo con nombre/equipo/razon), "
    "tiros (total_esperados, local_total, visitante_total, local_al_arco, visitante_al_arco, "
    "local_conversion, visitante_conversion), "
    "arqueros (arquero_local y arquero_visitante con nombre/atajadas_esperadas/porcentaje_efectividad/descripcion), "
    "corners (total_esperados, local_corners, visitante_corners, mas_de_9_prob, descripcion), "
    "arbitro (nombre, pais, estilo, promedio_amarillas_partido, promedio_rojas_partido, "
    "penales_por_partido, tendencia, datos_disponibles), "
    "analisis_tacttico, factores_clave (lista de 4), confianza_analisis, fuente_datos."
)


_request_log = defaultdict(list)


def is_rate_limited(ip: str) -> bool:
    now = time.time()
    window = 3600
    limit = settings.RATE_LIMIT_PER_HOUR
    _request_log[ip] = [t for t in _request_log[ip] if now - t < window]
    if len(_request_log[ip]) >= limit:
        return True
    _request_log[ip].append(now)
    return False


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


class HealthCheckView(APIView):
    def get(self, request):
        return Response({
            'status': 'ok',
            'service': 'ScoutBot API',
        })


class AnalyzeMatchView(APIView):
    def post(self, request):
        ip = get_client_ip(request)
        if is_rate_limited(ip):
            return Response(
                {'error': 'Límite de solicitudes alcanzado. Intenta en una hora.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        query = request.data.get('query', '').strip()
        if not query:
            return Response(
                {'error': 'El campo "query" es requerido.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(query) > 300:
            return Response(
                {'error': 'La consulta es demasiado larga.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        api_key = settings.GROQ_API_KEY
        if not api_key:
            return Response(
                {'error': 'API key de Groq no configurada.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            client = Groq(api_key=api_key)

            # Usamos llama-3.3-70b-versatile que es súper rápido y estable.
            # Tiene un contexto gigantesco, por lo que nunca dará error 413.
            response = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': query},
                ],
                max_tokens=4000,
                temperature=0.3,
            )

            final_text = response.choices[0].message.content

            clean = final_text.replace('```json', '').replace('```', '').strip()
            start = clean.find('{')
            end = clean.rfind('}') + 1
            if start == -1 or end == 0:
                return Response(
                    {'error': 'No se pudo generar el análisis. Intenta con otro partido.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            analysis = json.loads(clean[start:end])
            return Response({'data': analysis}, status=status.HTTP_200_OK)

        except json.JSONDecodeError:
            return Response(
                {'error': 'Error al procesar la respuesta del modelo.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            error_msg = str(e)
            if '429' in error_msg or 'rate' in error_msg.lower():
                return Response(
                    {'error': 'Demasiadas solicitudes. Espera un momento.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )
            return Response(
                {'error': f'Error interno: {error_msg}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
