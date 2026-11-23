# Limitações desta versão e como explicá-las

Esta versão lê a API pública V1 da Solvis. Ela não tem endpoint de métricas: o motor baixa as avaliações, reconstrói os ids e calcula com as regras das telas. Algumas coisas a API simplesmente não entrega.

## O que não está disponível

| Pedido | Por quê | O que oferecer |
|---|---|---|
| Tom / sentimento dos comentários | A análise do Radar não sai na API pública | `tag_mentions` e `comments` |
| Temas com base "comentários analisados pelo Radar" | Idem | `tag_mentions` (base: comentários com tag) |
| Resumo, sugestão ou matriz GUT do Radar | Idem | Trechos de `comments` |
| Regras de Data Quality que falharam | A API traz só confiável/reprovada/não verificada | `data_quality_summary` |
| Turno cadastrado | Não sai na API | `hour_block` |
| Taxa de resposta, convites, envios | Não há denominador | `evaluation_count` |
| Respostas individuais de e-mail, telefone, CPF, CNPJ, data e numérico | Privacidade: o motor nunca guarda | Contagens |
| Texto de perguntas protegidas por LGPD | Só é guardado (mascarado) se o usuário autorizar; a pergunta é feita no primeiro uso e registrada com `setup --lgpd-text on\|off`. Sem decisão, não assuma "não": pergunte | Contagens; com autorização, `comments` traz o texto mascarado |

## Comportamentos da API que o motor trata

| Situação | O que o motor faz | O que dizer ao usuário |
|---|---|---|
| Duas perguntas do mesmo tipo com o mesmo texto | A API devolve só o texto; o motor separa pela alternativa escolhida (quando as gêmeas têm alternativas diferentes) e pela ordem das respostas, e recusa a métrica quando sobra resposta sem dono | "A pesquisa repete esse texto em mais de uma pergunta, e a API não diz qual delas foi respondida em N casos; por isso não dá para calcular esta pergunta." Para métricas disponíveis com `answers_assigned_by_order`, o número pode ser citado |
| Pergunta com regra de entrada ou ramificação | O motor lê as regras do questionário e as expõe em `questionnaire` (`flow`) e no aviso `conditional_question`. A API não traz as perguntas exibidas: o motor infere quem viu cada uma refazendo o caminho de cada avaliação com as regras e as respostas (`exposure`). Premissas: a pesquisa começa na pergunta 1; perguntas escondidas por variação de pesquisa não aparecem na API; em avaliação incompleta o caminho vai até a última pergunta com resposta gravada. A atribuição de respostas de texto repetido ainda não usa as regras | "Esta pergunta só aparece para quem <condição>; pelas regras do questionário, N avaliações a viram e M responderam." Diga que é inferido |
| Avaliações repetidas (mesmo texto, minutos de diferença) | Não remove: sem Data Quality, o sistema não marca repetição | Mencionar que podem inflar contagens, se aparecerem |
| A API pode devolver lista vazia para um período mesmo havendo avaliações | O motor confere dia a dia e avisa (`possible_silent_failure`, `suspicious_empty_days`) | "A API não devolveu avaliações de X a Y. Vale conferir na tela de resultados." |
| A API recusa uma janela (HTTP 400) | O motor divide a janela até isolar o trecho e o exclui (`incomplete_coverage`) | "Os números excluem o trecho de <datas>, que a API não entregou." |
| Download longo | O motor baixa no máximo ~90 s por comando e continua no seguinte (`sync_incomplete`). Para períodos longos, `sync --until-complete --budget 300` repete as rodadas sozinho; as janelas são baixadas 4 a 4 em paralelo | "Ainda estou baixando os dados; continuo em seguida." |

## Atualização dos dados

O motor guarda as avaliações num cache local. Dias recentes (até 3 dias atrás) são atualizados depois de 1 hora; hoje, depois de 10 minutos; dias antigos, são baixados de novo depois de 7 dias. A atualização dos dias recentes pede só as avaliações recebidas desde o último download. `--refresh` força um novo download. `freshness.fetched_newest` diz quando foi o último.

## Mês inicial e ressincronização

O motor só baixa dados a partir do mês que o usuário escolhe na primeira consulta (`config --start-month`); pedidos de períodos anteriores são recusados até ele antecipar o mês. Isso evita varrer anos sem dados e acelera o primeiro download.

Tags (e qualquer outra mudança feita depois que a avaliação foi baixada) só chegam ao cache quando o dia é baixado de novo. Rotina sugerida, a ser agendada pelo usuário (a skill não agenda sozinha), para cada pesquisa que ele acompanha:

| Quando | Comando |
|---|---|
| Todo dia | `sync --survey ID --period yesterday --refresh` |
| Toda segunda-feira | `sync --survey ID --period last_week --refresh` |
| No dia 1 de cada mês | `sync --survey ID --period last_month --refresh` |

## Primeiro uso

A primeira consulta de um período baixa as avaliações da API e pode levar de alguns segundos a minutos, conforme o volume. As seguintes usam o cache.
