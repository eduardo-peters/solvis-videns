"""Parâmetros comuns das tools (nome: (tipo JSON, descrição))."""


PERIOD = {"period": ("string", "yesterday, today, last_7_days, this_month, last_month ou month:AAAA-MM"),
          "start": ("string", "Data inicial AAAA-MM-DD (em vez de period)"),
          "end": ("string", "Data final AAAA-MM-DD (em vez de period)")}
SURVEY = {"survey": ("string", "Nome da pesquisa como o usuário disse (ex.: 'Satisfação')")}
QUESTION = {"question": ("string", "Texto ou número da pergunta (ex.: 'Atendimento', '2')")}
