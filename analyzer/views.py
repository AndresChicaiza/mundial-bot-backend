import json
import time
from collections import defaultdict

from duckduckgo_search import DDGS
from groq import Groq
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

SYSTEM_PROMPT = (
    "Eres ScoutBot, analista experto del Mundial 2026. "
    "Responde SOLO con JSON válido sin markdown.\n\n"
    "=== REGLAS GENERALES ===\n"
    "- Usa el contexto web proporcionado en la consulta como base principal del análisis.\n"
    "- Si el contexto es insuficiente y no hay datos exactos, usa promedios históricos realistas del equipo usando tu conocimiento base, aclarando que son estimados.\n"
    "- El JSON debe ser parseable directamente, sin caracteres de control ni comillas sin escapar.\n"
    "- Los valores numéricos deben ser números, no strings.\n\n"
    "=== ANÁLISIS PONDERADO POR RANKING FIFA (obligatorio) ===\n"
    "1. Identifica el Ranking FIFA actual de ambos equipos del partido.\n"
    "2. Para CADA equipo, identifica sus últimos 5 partidos jugados y CONTRA QUIÉN.\n"
    "3. Clasifica la dificultad de cada rival según su Ranking FIFA en ese momento:\n"
    "   - Top 10 = 'alta' | 11-30 = 'media-alta' | 31-60 = 'media' | 60+ = 'baja'\n"
    "4. Pondera cada resultado según esa dificultad: una victoria contra un Top 10\n"
    "   vale más que una goleada contra un equipo fuera del Top 60. Una derrota\n"
    "   contra un rival Top 5 no debe penalizar tanto como una derrota contra un\n"
    "   equipo de ranking bajo.\n"
    "5. Calcula un 'índice de forma ponderado' (0-100) para cada equipo que\n"
    "   refleje la calidad de la competencia enfrentada, no solo W/D/L en bruto.\n"
    "6. Considera la brecha de ranking FIFA entre ambos equipos del partido actual:\n"
    "   a mayor brecha, mayor peso debe tener el ranking en la probabilidad final.\n"
    "7. Llena el campo 'contexto_ranking_fifa' del JSON con este análisis completo,\n"
    "   y usa esa conclusión para ajustar coherentemente 'probabilidades_resultado'.\n\n"
    "=== VERIFICACIÓN OBLIGATORIA DE PLANTILLA (anti-alucinación, CRÍTICO) ===\n"
    "1. SOLO puedes nombrar jugadores que aparezcan EXPLÍCITAMENTE en el contexto\n"
    "   web proporcionado como parte de la convocatoria, alineación o plantilla\n"
    "   ACTUAL para el Mundial 2026. NUNCA uses tu conocimiento general o memoria\n"
    "   de qué jugadores 'suelen' representar a un país.\n"
    "2. PROHIBIDO mencionar jugadores retirados de la selección, retirados del\n"
    "   fútbol profesional, o que no figuren en el contexto de búsqueda como\n"
    "   convocados a este Mundial 2026. Ejemplo de error grave: nombrar a un\n"
    "   ícono histórico de un país (ej. un delantero ya retirado) solo porque es\n"
    "   famoso — eso es una alucinación y está terminantemente prohibido.\n"
    "3. Si el contexto web NO menciona jugadores específicos de un equipo con\n"
    "   suficiente claridad, usa términos genéricos como 'delantero titular' o\n"
    "   'principal referente ofensivo (no confirmado por fuente)' en lugar de\n"
    "   inventar un nombre.\n"
    "4. En el campo 'verificacion_plantilla', lista únicamente los jugadores que\n"
    "   SÍ aparecieron respaldados por el contexto de búsqueda, y en 'nota'\n"
    "   declara honestamente si la convocatoria pudo confirmarse o si hay\n"
    "   incertidumbre.\n"
    "5. Esta regla aplica a TODOS los campos del JSON: goleadores_probables,\n"
    "   jugadores_en_riesgo, arquero_local/visitante, etc. Cero jugadores\n"
    "   inventados o desactualizados en ningún campo.\n\n"
    "=== ESQUEMA JSON DE RESPUESTA ===\n"
    "El JSON debe tener la siguiente estructura estricta:\n"
    "{\n"
    "  \"contexto_ranking_fifa\": {\n"
    "    \"equipo_local\": {\n"
    "      \"ranking_fifa\": 0,\n"
    "      \"indice_forma_ponderado\": 0,\n"
    "      \"ultimos_5_partidos\": [\n"
    "        {\n"
    "          \"rival\": \"string\",\n"
    "          \"ranking_rival\": 0,\n"
    "          \"resultado\": \"string\",\n"
    "          \"dificultad\": \"alta|media-alta|media|baja\",\n"
    "          \"puntuacion_ponderada\": 0\n"
    "        }\n"
    "      ]\n"
    "    },\n"
    "    \"equipo_visitante\": {\n"
    "      \"ranking_fifa\": 0,\n"
    "      \"indice_forma_ponderado\": 0,\n"
    "      \"ultimos_5_partidos\": [\n"
    "        {\n"
    "          \"rival\": \"string\",\n"
    "          \"ranking_rival\": 0,\n"
    "          \"resultado\": \"string\",\n"
    "          \"dificultad\": \"alta|media-alta|media|baja\",\n"
    "          \"puntuacion_ponderada\": 0\n"
    "        }\n"
    "      ]\n"
    "    },\n"
    "    \"brecha_ranking\": 0,\n"
    "    \"conclusion_ajuste\": \"string\"\n"
    "  },\n"
    "  \"verificacion_plantilla\": {\n"
    "    \"jugadores_confirmados_local\": [\"string\"],\n"
    "    \"jugadores_confirmados_visitante\": [\"string\"],\n"
    "    \"nota\": \"string\"\n"
    "  },\n"
    "  \"partido\": {\n"
    "    \"equipo_local\": \"string\",\n"
    "    \"equipo_visitante\": \"string\",\n"
    "    \"fecha\": \"string\",\n"
    "    \"estadio\": \"string\",\n"
    "    \"fase\": \"string\"\n"
    "  },\n"
    "  \"probabilidades_resultado\": {\n"
    "    \"victoria_local\": 0,\n"
    "    \"empate\": 0,\n"
    "    \"victoria_visitante\": 0,\n"
    "    \"marcadores_exactos\": [\n"
    "      { \"marcador\": \"string\", \"probabilidad\": 0 }\n"
    "    ],\n"
    "    \"descripcion\": \"string\"\n"
    "  },\n"
    "  \"goles\": {\n"
    "    \"total_esperado\": 0,\n"
    "    \"local_esperado\": 0,\n"
    "    \"visitante_esperado\": 0,\n"
    "    \"ambos_anotan_prob\": 0,\n"
    "    \"mas_de_2_5_prob\": 0,\n"
    "    \"goleadores_probables\": [\n"
    "      { \"nombre\": \"string\", \"equipo\": \"string\", \"probabilidad\": 0, \"razon\": \"string\" }\n"
    "    ]\n"
    "  },\n"
    "  \"tarjetas\": {\n"
    "    \"amarillas_esperadas\": 0,\n"
    "    \"local_amarillas\": 0,\n"
    "    \"visitante_amarillas\": 0,\n"
    "    \"rojas_prob\": 0,\n"
    "    \"jugadores_en_riesgo\": [\n"
    "      { \"nombre\": \"string\", \"equipo\": \"string\", \"razon\": \"string\" }\n"
    "    ]\n"
    "  },\n"
    "  \"tiros\": {\n"
    "    \"total_esperados\": 0,\n"
    "    \"local_total\": 0,\n"
    "    \"visitante_total\": 0,\n"
    "    \"local_al_arco\": 0,\n"
    "    \"visitante_al_arco\": 0,\n"
    "    \"local_conversion\": 0,\n"
    "    \"visitante_conversion\": 0\n"
    "  },\n"
    "  \"arqueros\": {\n"
    "    \"arquero_local\": {\n"
    "      \"nombre\": \"string\",\n"
    "      \"atajadas_esperadas\": 0,\n"
    "      \"porcentaje_efectividad\": 0,\n"
    "      \"descripcion\": \"string\"\n"
    "    },\n"
    "    \"arquero_visitante\": {\n"
    "      \"nombre\": \"string\",\n"
    "      \"atajadas_esperadas\": 0,\n"
    "      \"porcentaje_efectividad\": 0,\n"
    "      \"descripcion\": \"string\"\n"
    "    }\n"
    "  },\n"
    "  \"corners\": {\n"
    "    \"total_esperados\": 0,\n"
    "    \"local_corners\": 0,\n"
    "    \"visitante_corners\": 0,\n"
    "    \"mas_de_9_prob\": 0,\n"
    "    \"descripcion\": \"string\"\n"
    "  },\n"
    "  \"arbitro\": {\n"
    "    \"nombre\": \"string\",\n"
    "    \"pais\": \"string\",\n"
    "    \"estilo\": \"string\",\n"
    "    \"promedio_amarillas_partido\": 0,\n"
    "    \"promedio_rojas_partido\": 0,\n"
    "    \"penales_por_partido\": 0,\n"
    "    \"tendencia\": \"string\",\n"
    "    \"datos_disponibles\": \"string\"\n"
    "  },\n"
    "  \"analisis_tactico\": \"string\",\n"
    "  \"factores_clave\": [\"string\"],\n"
    "  \"confianza_analisis\": 0,\n"
    "  \"fuente_datos\": \"string\"\n"
    "}"
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


def perform_web_search(query: str) -> str:
    """Realiza una búsqueda web para inyectar contexto actualizado sobre el partido."""
    try:
        search_term = f"plantilla y ultimos partidos {query} mundial 2026"
        with DDGS() as ddgs:
            # Trae los 5 primeros resultados
            results = list(ddgs.text(search_term, max_results=5))
            
            context = "=== CONTEXTO WEB RECIENTE ===\n"
            for r in results:
                context += f"- {r.get('title')}: {r.get('body')}\n"
            return context
    except Exception as e:
        # Si falla la búsqueda, devolvemos un aviso para que el LLM lo sepa
        print(f"Error en duckduckgo_search: {e}")
        return "=== CONTEXTO WEB RECIENTE ===\nNo se pudo obtener información web en este momento."


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
            # Buscar en internet contexto fresco
            web_context = perform_web_search(query)
            
            # Unir el contexto web a la petición del usuario
            augmented_query = f"{web_context}\n\n=== PETICIÓN DEL USUARIO ===\n{query}"

            client = Groq(api_key=api_key)

            # Usamos llama-3.3-70b-versatile que es súper rápido y estable.
            # Tiene un contexto gigantesco, por lo que nunca dará error 413.
            response = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': augmented_query},
                ],
                max_tokens=6000,
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
