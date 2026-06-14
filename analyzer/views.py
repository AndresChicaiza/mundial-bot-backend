import json
import time
from collections import defaultdict

import anthropic
from django.conf import settings
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

SYSTEM_PROMPT = """Eres ScoutBot, el analista estadístico más completo del Mundial de Fútbol.
Cuando el usuario te pida estadísticas o probabilidades de un partido, proporciona el análisis más detallado posible basándote en tu conocimiento histórico, estado de forma conocido de los equipos y proyecciones estadísticas realistas.

Busca analizar y estimar:
- Historial reciente de ambos equipos
- Estadísticas head-to-head entre los equipos
- Estado de forma, posibles lesiones, suspensiones
- Información sobre el árbitro designado (estimado si no hay)
- Estadísticas del torneo actual o proyecciones

Luego, responde ÚNICAMENTE con un JSON válido (sin markdown, sin texto antes ni después) con esta estructura exacta:

{
  "partido": {
    "equipo_local": "Nombre del equipo",
    "equipo_visitante": "Nombre del equipo",
    "fecha": "DD/MM/YYYY",
    "estadio": "Nombre del estadio",
    "fase": "Fase del torneo"
  },
  "probabilidades_resultado": {
    "victoria_local": 45,
    "empate": 28,
    "victoria_visitante": 27,
    "descripcion": "Texto explicativo de 1-2 oraciones"
  },
  "goles": {
    "total_esperado": 2.4,
    "local_esperado": 1.4,
    "visitante_esperado": 1.0,
    "ambos_anotan_prob": 58,
    "mas_de_2_5_prob": 52,
    "goleadores_probables": [
      {"nombre": "Jugador", "equipo": "Equipo", "probabilidad": 35, "razon": "Explicación breve"},
      {"nombre": "Jugador", "equipo": "Equipo", "probabilidad": 28, "razon": "Explicación breve"},
      {"nombre": "Jugador", "equipo": "Equipo", "probabilidad": 22, "razon": "Explicación breve"},
      {"nombre": "Jugador", "equipo": "Equipo", "probabilidad": 18, "razon": "Explicación breve"}
    ]
  },
  "tarjetas": {
    "amarillas_esperadas": 3.2,
    "local_amarillas": 1.8,
    "visitante_amarillas": 1.4,
    "rojas_prob": 18,
    "jugadores_en_riesgo": [
      {"nombre": "Jugador", "equipo": "Equipo", "razon": "Motivo del riesgo"},
      {"nombre": "Jugador", "equipo": "Equipo", "razon": "Motivo del riesgo"}
    ]
  },
  "tiros": {
    "total_esperados": 22,
    "local_total": 12,
    "visitante_total": 10,
    "local_al_arco": 5,
    "visitante_al_arco": 4,
    "local_conversion": 28,
    "visitante_conversion": 25
  },
  "arqueros": {
    "arquero_local": {
      "nombre": "Nombre del arquero",
      "atajadas_esperadas": 4,
      "porcentaje_efectividad": 82,
      "descripcion": "Breve análisis"
    },
    "arquero_visitante": {
      "nombre": "Nombre del arquero",
      "atajadas_esperadas": 5,
      "porcentaje_efectividad": 78,
      "descripcion": "Breve análisis"
    }
  },
  "corners": {
    "total_esperados": 9.5,
    "local_corners": 5.5,
    "visitante_corners": 4.0,
    "mas_de_9_prob": 48,
    "descripcion": "Análisis breve"
  },
  "arbitro": {
    "nombre": "Nombre del árbitro",
    "pais": "País",
    "estilo": "Estricto / Permisivo / Equilibrado",
    "promedio_amarillas_partido": 3.8,
    "promedio_rojas_partido": 0.2,
    "penales_por_partido": 0.4,
    "tendencia": "Descripción de su estilo y cómo puede afectar el partido",
    "datos_disponibles": true
  },
  "analisis_tacttico": "Párrafo de 3-4 oraciones sobre el análisis táctico.",
  "factores_clave": [
    "Factor importante 1",
    "Factor importante 2",
    "Factor importante 3",
    "Factor importante 4"
  ],
  "confianza_analisis": 82,
  "fuente_datos": "Descripción de las fuentes usadas para el análisis"
}

IMPORTANTE:
- Si no encuentras datos exactos, usa promedios históricos realistas o proyecciones fundamentadas
- El JSON debe ser parseable directamente, sin caracteres especiales problemáticos"""


# Simple in-memory rate limiting (resets on dyno restart)
_request_log = defaultdict(list)

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    window = 3600  # 1 hora
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
        return Response({'status': 'ok', 'service': 'ScoutBot API'})


class AnalyzeMatchView(APIView):
    def post(self, request):
        # Rate limiting
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

        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            return Response(
                {'error': 'API key no configurada.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            client = anthropic.Anthropic(api_key=api_key)

            # Usaremos Claude 3.5 Sonnet (o 3.7 si está disponible), que es excelente para análisis
            # Como no tenemos una API de búsqueda web real configurada, omitimos la herramienta
            # y pedimos a Claude que use su conocimiento o simule proyecciones para partidos futuros.
            
            response = client.messages.create(
                model='claude-3-5-sonnet-20241022',
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': query}],
            )

            final_text = ''.join(
                block.text for block in response.content
                if hasattr(block, 'text')
            )

            # Parse JSON from response
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
        except anthropic.APIError as e:
            return Response(
                {'error': f'Error de API: {str(e)}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            return Response(
                {'error': f'Error interno: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
