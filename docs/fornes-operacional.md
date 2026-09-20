# Leitura automática de estrutura — versão 1

Implementação inspirada na pesquisa fornecida das sete aulas distintas acessíveis da [playlist de Alexandre Fornes](https://www.youtube.com/playlist?list=PLarwpkrmmCPOZrYeFVGWj4XwcriWlw-f5). A lista contém uma duplicação e três vídeos privados. A pesquisa consultou legendas automáticas; as marcações visuais não foram integralmente verificadas. Esta tradução em regras não é reprodução perfeita nem estratégia com rentabilidade comprovada.

## Dados e integração

Binance Spot BTC/USDT, 200 velas fechadas por período: diário, 4 horas e 1 hora. Esta é uma adaptação à disponibilidade do painel, não uma alegação de equivalência a todas as combinações das aulas. A validação de origem já existente rejeita lacunas, OHLCV inválido e dados antigos e exclui velas abertas antes do cálculo. A coleta ocorre a cada minuto. Falha ou idade de coleta de 120 segundos desabilita a leitura atual no painel e remove o plano da resposta corrente da API.

`structure` integra o snapshot versionado e seu hash, com os mesmos dados de entrada, em `/live/status` (proxy `/api/engine/status`) e histórico. O gráfico usa exatamente essas velas, sem uma segunda fonte de preços. Histórico é auditoria, nunca autorização atual.

O Triple Screen de EMA/MACD permanece separado, em detalhes recolhidos. Sua carteira e seu backtest não operam a nova estratégia de estrutura. O novo plano é apenas referência condicional, não aciona operações reais nem simuladas; não há backtest de rentabilidade de estrutura nesta entrega.

## Parâmetros objetivos adotados

- Pivô maior: extremo estrito com 2 velas à esquerda e 2 à direita; interno: 1 de cada lado. Empates não formam pivô. Disponibilidade registrada no fechamento da última vela da direita; gráficos começam a marcação nessa confirmação, não retroagem o sinal até a vela do extremo.
- Primeiro rompimento por fechamento, com extremo oposto disponível, estabelece direção. Continuação exige outro fechamento além do extremo mais recente na mesma direção. O último extremo oposto confirmado nesse rompimento fica protegido. Uma quebra contrária interna não altera a direção maior enquanto não perder sua proteção.
- Perda por fechamento do extremo protegido gera possível mudança (CHoCH) e volta ao estado sem direção. Não confirma reversão na mesma vela. Um fechamento posterior pode definir nova direção. Uma passagem por pavio que fecha de volta gera observação de varredura; não conta como rompimento. Uma ocorrência por extremo é registrada.
- Impulso: última continuação de 4h alinhada ao diário, do extremo oposto protegido ao extremo da vela de rompimento. Âncoras congeladas no instante do rompimento. Linha de metade e região de devolução 61,8%–78,6%. Não estende automaticamente o fim para extremos descobertos depois.
- Região de reação (proxy de order block): última vela de direção oposta nas 10 anteriores a um rompimento cujo corpo seja pelo menos 1,5 vez a amplitude média das 14 velas anteriores disponíveis. Faixa usa a máxima e mínima completas. Fechamento além da borda contrária invalida. Não identifica ordens institucionais.
- Faixa de três velas (FVG): mínima da terceira acima da máxima da primeira (alta) ou máxima da terceira abaixo da mínima da primeira (baixa). Criada no fechamento da terceira. Toque parcial registrado; pavio cobrindo toda a faixa encerra como preenchida. Os extremos originais permanecem desenhados, com o estado explicitado.
- Interesse potencial: máximas/mínimas confirmadas, e pares consecutivos do mesmo tipo a até 0,15% de distância. Não é mapa de stops nem conhecimento da intenção de participantes.

## Sequência condicional

1. Direção diária por estrutura e continuação anterior alinhada nas 4h.
2. Histórico de 1h cobre integralmente o tempo desde o rompimento de 4h. Se a janela de 200 horas não cobrir, aguarda um novo contexto.
3. Após a região ficar conhecida, chegada à região sem fechamento de 1h atravessando sua borda contrária. Atravessar cancela essa hipótese até um novo impulso.
4. Na chegada ou depois dela, varredura de extremo conhecido dentro da região, com retorno na direção principal.
5. Em vela posterior, rompimento confirmado na direção principal em 1h.
6. Faixa de três velas na mesma direção confirmada na vela de rompimento ou na seguinte e ainda não completamente preenchida. Este é o filtro de deslocamento adotado; não se pressupõe presença de volume institucional.
7. Em vela posterior à faixa e ao rompimento, retorno ao nível rompido com fechamento a favor. Somente o primeiro retorno dessa sequência, quando é a última vela fechada, habilita candidato. Um sinal antigo não permanece ativo nas velas seguintes.
8. Referência de entrada = fechamento dessa vela, stop = origem do impulso. Alvo = extremo confirmado mais próximo à frente, de diário ou 4h, que ainda não foi revisitado desde a confirmação. Não pula obstáculo próximo para escolher um mais distante. Retorno líquido estimado / risco com custos deve ser >= 3. Custos adotados: 0,15% por lado; reward líquido = distância ao alvo menos custos entrada/saída; risco inclui custos entrada/stop. Sem alvo adequado, nenhum plano é publicado.

As marcações e descrições dos três períodos são independentes desses bloqueios; aparecem mesmo quando nenhuma entrada é válida. Um plano de estrutura não significa aprovação dos filtros de médias, calendário ou carteira. Não há autorização de execução neste módulo.

## Interface e limites

Gráfico interativo abre em 4 horas, com alternância para diário e 1 hora, camadas de regiões, extremos, eventos e regiões encerradas. Clique/toque ou seletor por teclado mostra valores e horário da vela. Os eventos numerados também são botões. No máximo seis regiões técnicas recentes, mais a região de interesse, e oito eventos, para evitar excesso de marcações. Trocar de período preserva análise própria. Históricos maiores podem alterar a inicialização da estrutura; versão e janela são explícitas.

Não implementa contagem Elliott/Wyckoff, perfil exato de volume por preço, inferência de ordens de bancos ou DCA. RSI já existe no módulo anterior como indicador auxiliar, mas não é filtro desta sequência. Acumulação periódica e variação de aporte são decisões separadas de trading.

## Referências fornecidas pela pesquisa

- [Introdução](https://www.youtube.com/watch?v=ZeV4abHG42I)
- [Aula 3](https://www.youtube.com/watch?v=5EDzCeyxrNo)
- [Aula 4](https://www.youtube.com/watch?v=agv-p9CAJ6Q)
- [Estrutura](https://www.youtube.com/watch?v=1oCCtRrh6Y0)
- [Liquidez](https://www.youtube.com/watch?v=jqWaEM178j0)
- [Filtros](https://www.youtube.com/watch?v=AFBlyt7ZEes)
- [DCA, separado do operacional](https://www.youtube.com/watch?v=8AXAnc9hMA4)
