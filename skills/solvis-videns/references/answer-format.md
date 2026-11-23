# Formato da resposta

## Regras

1. **Comece pelo que foi perguntado.** A primeira frase responde com o número principal.
2. **Todo número com n e período.** "NPS de 41 (312 respostas, 1 a 31/10/2026)".
3. **Use o `display` do envelope** e os campos `*_display` dos percentuais. Vírgula decimal em pt-BR. NPS sem "%". Médias com a escala ("4,3 de 1 a 5"). Em escala de 0 a 100 a média aparece com "%", como nas telas: é a média dos valores, não "% de satisfeitos".
4. **Declare o que não é óbvio:** política de confiabilidade em pesquisa com Data Quality, filtros, mapeamentos ("usei a pergunta 3 como CSAT"), escolha entre nomes ambíguos, cobertura incompleta da API, período em andamento.
5. **Separe fato de leitura.** Números e citações são fato. Hipóteses vêm marcadas: "vale investigar", "pode indicar". Nada de causa provada a partir de comentários ou tags.
6. **Não use conhecimento externo** sobre o setor, concorrentes ou "NPS bom de mercado", a menos que o usuário forneça a referência; nesse caso, atribua a ele.
7. **Diga o que falta.** Se a pergunta não pode ser respondida com o modelo, diga o que não existe e ofereça a alternativa mais próxima.
8. **Cite as consultas.** Termine com a linha `Fontes:` e os `query_id` usados, mais quando os dados foram baixados (`freshness.fetched_newest_sao_paulo`). Em recusa ou erro, sem `query_id`: `Fontes: nenhuma consulta com resultado (motivo: <código do erro>)`.

## Modelo curto (pergunta direta)

> O NPS da Pesquisa Lojas em outubro de 2026 foi 15, com 20 respostas, 15 pontos acima de outubro de 2025 (0, 10 respostas). A melhora veio de menos detratores: 35,0% contra 50,0% no ano anterior. A amostra é pequena (menos de 30 respostas por período).
>
> Fontes: q_c20ad66b · dados da API Solvis baixados em 17/11/2026 20:18

## Modelo de relatório (panorama)

Para diagnóstico de queda, use o formato do playbook 2 (texto corrido, até 8 frases). Relatório, deck ou página que vai sair da conversa: antes, peça e use os materiais de referência do cliente ([materials.md](materials.md)); a estrutura abaixo é a mínima, o visual e o vocabulário vêm do perfil de marca.

```
## <Título com pesquisa e período>

**Resumo:** 2 a 3 frases com os números principais.

### Números
| Indicador | Valor | n | Variação |
|---|---|---|---|

### O que os respondentes disseram      (se houver comentários ou tags)
- <tag>: <menções> comentários (<%> dos comentários com tag) — "<trecho curto>"

### Pontos de atenção
- amostras pequenas, cobertura da API, políticas aplicadas, período parcial

### O que investigar                    (opcional, marcado como sugestão)

Fontes: <query_ids> · dados baixados em <freshness.fetched_newest_sao_paulo> · modelo <model_version>
```

## Quando o host não renderiza Markdown

Escreva texto corrido, uma ideia por frase, sem tabelas. Mantenha a linha de fontes.

## Idioma

Responda no idioma do usuário (`--locale en|es` muda o formato de `display`). Textos de pergunta, alternativa e comentário ficam no idioma original.
