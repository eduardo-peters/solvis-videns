# Protocolo de validação estatística de material analítico (pesquisas Solvis)

Protocolo que o comando `validate` aplica a cada afirmação de um material gerado. Os limiares abaixo são os do motor.

## Objetivo

Validar, contra a base de resultados da pesquisa do cliente e o questionário, com as respectivas perguntas e condicionais aplicadas a elas, cada afirmação de um material analítico (deck, relatório, canvas). Cada afirmação recebe um veredito com o critério aplicado. Não reescreva o material: produza o parecer.

## Regras gerais

Receba a base de resultados aplicada e referenciada no material analítico analisado. Todo cálculo roda em SQL ou código, nunca de cabeça.
Não aceite número do material sem recalcular. Não invente valor de referência.
Aplique os testes na ordem abaixo, com os limiares exatos indicados. Não crie critérios novos nem afrouxe os limiares.

## Fase 0. Reproduzir o recorte do material

1. Identifique no material: cliente, id da pesquisa, período e data e hora da extração.
2. Ache os bancos de resultado do período. Use FINAL e `_peerdb_is_deleted = 0` em todas as tabelas. Filtre o período por `started_at` (hora local da unidade).
3. Recorte de extração: aplique `created_at` < data/hora da extração convertida para UTC. Ajuste o corte, em passos de 1 minuto, até reproduzir o n total do material. Se reproduzir, registre o corte. Se não reproduzir, registre a diferença e siga com o corte mais próximo.
4. Leia o questionário: perguntas, tipos, alternativas e valores. Infira o roteamento pela própria base: cruze a presença de resposta em cada pergunta com a resposta da pergunta anterior e com `completed`. Defina para cada pergunta condicional:
   - **elegíveis**: quem, pela regra, deveria ver a pergunta;
   - **respondentes**: quem respondeu;
   - **abandonos**: elegíveis que não responderam.
5. Defina de forma fixa:
   - NPS = %promotores (9–10) − %detratores (0–6), sobre quem respondeu ao NPS;
   - canal Web = avaliação com linha em `web_access_infos`;
   - unidade ativa = unidade com ≥1 avaliação no período (diferente de unidade do cadastro);
   - propriedades de unidade = cadastro atual.

## Fase 1. Inventário de afirmações (antes de qualquer teste)

Percorra o material inteiro, seção por seção, incluindo títulos, textos de abertura, quadros, gráficos (valores no código), tabelas, rodapés, plano de ação e limitações. Liste cada afirmação verificável com: id da seção, texto exato e tipo, conforme a lista abaixo. Uma frase com várias afirmações vira várias linhas.

Tipos:

- **N** (número)
- **B** (base/denominador)
- **Q** (qualificador: "quase totalidade", "maioria", "lidera", "segundo maior", "todo mês", "estável", "sem X abaixo de Y", faixa "entre A e B")
- **E** (contagem ou lista de entidades: unidades, estados, "inclui as quatro…")
- **T** (tendência de agregado)
- **C** (comparação entre períodos ou unidades)
- **R** (ranking ou lista "top/onde se concentra/N abaixo de X")
- **X** (exemplos/referências, sem pretensão de ranking)
- **G** (destaque de grupo: "puxa a média", melhor e pior)
- **K** (contagem de palavras)
- **A** (tag/classificação de texto)
- **V** (citação literal)
- **P** (padrão em comentários: "surtos", "repetição diária")
- **L** (linguagem causal)
- **O** (coerência título × dado do próprio slide)
- **D** (taxa por dia ou semana)
- **U** (unidade citada em lista crítica ou no plano de ação)

## Fase 2. Testes por tipo (limiares fixos)

**N: reprodução numérica.** Recalcule com a definição do material. Confere: o valor recalculado, arredondado na precisão exibida, é igual ao exibido. Tolera-se 1 unidade na última casa quando o recalculado está a ≤0,05 da fronteira de arredondamento. Se não confere, teste se o número bate com outra base plausível (elegíveis × respondentes × chegaram à pergunta × total) antes de declarar divergência.

**B: base.** "viram", "exibida", "chegaram" ou "de quem não marcou X" exigem base de elegíveis. "responderam" e "de quem respondeu" exigem base de respondentes. Número certo para outra base, com rótulo errado: "base mal descrita".

**Q: qualificadores.**
- "quase totalidade" ou "quase sempre": ≥90%. "maioria": >50%. "metade": 45–55%.
- Ordinais ("lidera", "maior", "segundo maior", "pior", "melhor"): posição exata no ranking completo do mesmo recorte.
- "sem [período] abaixo de X": mínimo dos valores sem arredondar ≥ X − 0,5.
- Faixa "entre A e B desde T": todos os valores da janela dentro de [A, B], na precisão exibida.
- "todo mês", "sobe" ou "cresce": direção igual em todos os passos consecutivos E aprovação no teste T.
- "estável": variação entre primeiro e último período dentro do IC95.

**E: entidades.** Conte unidades ativas, não as do cadastro. Listas fechadas ("as quatro unidades X", "inclui A, B, C") devem bater com a contagem real do grupo. Contagens de "sem atributo" usam unidades ativas, com o número do cadastro informado à parte.

**T: tendência de agregado (teste de composição).** Obrigatório para toda tendência de rede, regional, UF ou grupo.
1. Conte as unidades do agregado em cada período.
2. Painel fixo = unidades com ≥1 avaliação em todos os períodos comparados. Calcule a métrica do painel e das unidades fora do painel.
3. Para cada passo consecutivo, calcule: Δagregado e Δpainel; z do Δpainel (diferença de proporções ou de NPS, erro-padrão abaixo); participação da composição = 1 − Δpainel/Δagregado.
4. Veredito "efeito de composição" se: na maioria dos passos, a participação da composição for >50% e o Δpainel tiver |z| < 1,96; ou o número de unidades do grupo mudar entre o primeiro e o último período e as unidades presentes no início não repetirem a tendência (Δ entre início e fim com |z| < 1,96 ou de sinal oposto).
5. Se a métrica principal do painel (NPS) se mover no sentido oposto ao afirmado, registre a contradição.

**C: comparação entre períodos ou unidades.**
- Erro-padrão do NPS: SE = √[(p + d − (p − d)²)/n], com p e d em proporção. Diferença de NPS: z = Δ / √(SE₁² + SE₂²). Proporções: teste z de duas proporções.
- Comparação agregada única (rede contra rede): robusta se |z| ≥ 1,96.
- Variações selecionadas entre muitas unidades (listas de quedas e recuperações): robusta se |z| ≥ 3,29 (Bonferroni para ~50 comparações, p < 0,001). Abaixo disso: "sinal a acompanhar".
- Informe sempre que as margens são otimistas, porque um mesmo respondente avalia várias vezes.

**R: ranking.** Recalcule o ranking completo com o critério declarado (incluindo n mínimo). Os itens listados devem ser exatamente os k primeiros. "N unidades abaixo de X" deve conter todas as que atendem o critério. Campos vazios ("—") com dado disponível contam como divergência de preenchimento. A base do ranking (todas as notas × só detratores) deve ser a declarada no título: "negativos" exige só detratores.

**X: exemplos/referências.** Cada item precisa atender ao critério declarado. Não precisa ser exaustivo.

**G: grupo pequeno.** Grupo com ≤2 unidades ou <1% das respostas não sustenta "puxa a média" nem pode ser o extremo de uma comparação em título sem essa marcação.

**K: contagem de palavras.** Teste variantes até reproduzir: só o campo de comentário × somando outros campos de texto; com e sem normalização de acentos; radical × palavra inteira; soma × união quando o rótulo junta termos. Registre a variante que reproduz e reporte os valores estritos (só comentário, palavra inteira quando o rótulo é palavra inteira, união) para total e detratores. Divergência se a reprodução exigir: misturar campos cujos autores não podem ser classificados no grupo comparado (por exemplo, quem pula o NPS); rótulo diferente da regra de contagem; soma onde o rótulo indica união.

**A: tags.** Base = comentários com ≥1 tag, por grupo. Informe a cobertura por mês. "Atribuição indevida" se a frase do material afirma algo que a tag não mede (turno, refeição, causa).

**V: citações.** Localize cada citação na base (busca sem acento, trecho de ≥4 palavras). Confere se existir com a unidade e a data atribuídas. Pequenas correções de digitação são aceitas. Não localizada = divergência.

**P: padrões em comentários.** Operacionalize o padrão com regra explícita (exemplo: "surto" = ≥10 comentários com o tema no mesmo dia e unidade, usando expressão regular declarada). Confirme cada caso citado: confirmado, parcial (≥ metade do limiar) ou não sustentado. Liste os casos que atendem o critério e não foram citados.

**L: linguagem causal.** Marque os verbos *transformar, causar, provocar, levar a, resultar em, fazer com que* aplicados a dados observacionais. Proponha a forma associativa ("aparece mais entre", "acompanha").

**O: coerência do título.** Todo título ou abertura com afirmação sobre o slide é testado contra os dados do próprio slide. Contradição = divergência.

**D: taxas.** Por dia: total ÷ dias corridos do período, fracionando dias parciais. Informe também a taxa por dia útil.

**U: unidades citadas.** Unidade em lista crítica com n = 0 no último período: sinalize coleta interrompida. Unidade no plano de ação precisa atender ao critério que motivou a ação. Se não atender, sinalize.

## Fase 3. Gravidade

**Correção obrigatória**, quando ocorrer qualquer um dos casos:
- número sem base plausível que o reproduza, com desvio relativo >10%;
- qualificador ou ordinal falso;
- contagem ou lista de entidades errada;
- tendência classificada como efeito de composição;
- ranking não exaustivo ou com base diferente da declarada;
- atribuição indevida de tag;
- contagem de palavras com mistura de bases ou rótulo diferente da regra;
- título que contradiz o dado do slide;
- taxa com desvio >10%;
- unidades do cadastro apresentadas como ativas.

**Ajuste**, quando ocorrer qualquer um dos casos:
- base mal descrita com número correto para outra base;
- desvio relativo ≤10% sem mudar a conclusão;
- faixa violada em ≤0,5 p.p.;
- linguagem causal;
- grupo pequeno em destaque;
- variação selecionada com |z| < 3,29 apresentada como fato;
- padrão parcial ou não sustentado em caso citado;
- unidade do plano fora do critério;
- texto quebrado ou inconsistência interna de digitação.

**Confere**: passou em todos os testes aplicáveis.

## Fase 4. Saída (sempre neste formato)

1. **Veredito**: "pode enviar" ou "não enviar como está", em uma frase, com o motivo principal.
2. **Como conferi**: pesquisa, período, corte de extração e se o n total foi reproduzido. Estado do Data Quality (campo `reliable`). Status das citações.
3. **O que confere**: lista agrupada por tema.
4. **Correções obrigatórias**: numeradas, na ordem de impacto na mensagem principal. Cada uma com: seção, o que o material diz, o que a base mostra (com n), critério violado.
5. **Ajustes de redação e método**: mesma estrutura, mais curta.
6. **Anexo**: tabela com uma linha por afirmação do inventário (seção · afirmação · tipo · valor no material · valor recalculado · teste · veredito · gravidade).

Antes de entregar, confira que cada afirmação do inventário tem veredito e que todo número citado no parecer vem de uma consulta executada nesta sessão.
