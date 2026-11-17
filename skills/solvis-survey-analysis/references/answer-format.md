# Formato da resposta

## Regras

1. **Comece pelo que foi perguntado.** A primeira frase responde à pergunta com o número principal.
2. **Todo número com n e período.** "NPS de 41 (312 respostas, 1 a 31/10/2026)".
3. **Use o `display` do envelope.** Vírgula decimal em pt-BR. NPS sem "%". Médias com a escala ("4,3 de 1 a 5").
4. **Declare o que não é óbvio:** política de confiabilidade quando for `reliable_only`, filtros aplicados, mapeamentos ("usei a pergunta 3 como CSAT"), escolha entre nomes ambíguos, cobertura parcial do Radar, período em andamento.
5. **Separe fato de leitura.** Números e citações são fato. Hipóteses vêm marcadas: "vale investigar", "pode indicar". Nada de causa provada a partir de comentários.
6. **Não use conhecimento externo** sobre o setor, concorrentes ou "NPS bom de mercado", a menos que o usuário forneça a referência; nesse caso, atribua a ele.
7. **Diga o que falta.** Se a pergunta não pode ser respondida com o modelo, diga o que não existe e ofereça a alternativa mais próxima.
8. **Cite as consultas.** Termine com a linha `Fontes:` e os `query_id` usados, mais o frescor (`dados até <watermark>`).

## Modelo curto (pergunta direta)

> O NPS da Pesquisa Lojas em outubro de 2026 foi 41, com 312 respostas, 14 pontos abaixo de outubro de 2025 (55, 298 respostas). A queda veio de mais detratores: 19,9% contra 11,4% no ano anterior. Foram consideradas só avaliações aprovadas pelo Data Quality.
>
> Fontes: q_7Hk2mP · dados até 17/11/2026 09:40 UTC

## Modelo de relatório (panorama ou diagnóstico)

```
## <Título com pesquisa e período>

**Resumo:** 2 a 3 frases com os números principais.

### Números
| Indicador | Valor | n | Variação |
|---|---|---|---|

### O que os respondentes disseram      (se houver comentários/temas)
- <tema>: <menções> comentários (<%>) — "<trecho curto>"

### Pontos de atenção
- amostras pequenas, cobertura do Radar, políticas aplicadas, período parcial

### O que investigar                    (opcional, marcado como sugestão)

Fontes: <query_ids> · dados até <watermark> · modelo <model_version>
```

## Quando o host não renderiza Markdown

Escreva texto corrido, uma ideia por frase, sem tabelas. Mantenha a linha de fontes.

## Idioma

Responda no idioma do usuário. Rótulos de métricas e dimensões têm versões pt, en e es em `metrics.yaml` e `dimensions.yaml`. Textos de pergunta, alternativa e comentário ficam no idioma original.
