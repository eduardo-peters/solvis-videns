"""Motor local da skill solvis-videns.

Lê a API pública V1 da Solvis, normaliza as respostas num modelo por id
(avaliação, pergunta, alternativa) e calcula as métricas com as mesmas
regras das telas de resultados. A LLM nunca calcula: ela chama este motor e
cita o envelope que ele devolve.
"""

ENGINE_VERSION = "0.2.0"
MODEL_VERSION = "pilot-1.0.0"
USER_AGENT = "solvis-videns/" + ENGINE_VERSION
