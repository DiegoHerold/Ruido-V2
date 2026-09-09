# Modelo da planilha de entrada

Use `CPF` para o funcionário consultado. O contexto de procuração vem na própria linha e nunca reaproveita o CPF do funcionário.

| Coluna | Obrigatória | Uso |
| --- | --- | --- |
| `CPF` | Sim | CPF do funcionário a consultar. |
| `Colaborador` | Não | Conferência visual do resultado. |
| `Tipo Procuração` | Sim | `Pessoa Jurídica` ou `Pessoa Física`. Também aceita os aliases `Tipo Pessoa`, `Tipo de Pessoa`, `Pessoa` e `Perfil Procuração`. |
| `CNPJ Representado` ou `CNPJ` | Condicional | Obrigatório para `Pessoa Jurídica`; identifica a empresa representada. |
| `CPF Representado` | Condicional | Obrigatório para `Pessoa Física`; identifica a pessoa representada. |
| `Ano` | Não | Data de início da exposição, no formato `dd/mm/aaaa` (por exemplo, `02/03/2026`). Preenchida automaticamente pela automação com o valor lido no eSocial ao concluir a linha; se você já preencher com um valor esperado, a automação valida o formato e confere contra o que leu no eSocial. |
| `Intensidade` | Não | Intensidade da exposição. Preenchida automaticamente pela automação com o valor lido no eSocial ao concluir a linha; se preenchida antes, é conferida contra o valor lido. |
| `Agente Nocivo` | Não | Informativo. A automação consulta sempre e somente o código fixo `02.01.001 - Ruído`. |
| `LOG` | Não | Campo livre da origem. Se não houver o agente fixo, a automação escreve `Não há Agente de Ruído`. |
| `Status` | Não | Deixe em branco para consultar. Ao finalizar uma linha, a automação grava `Concluido`; em uma nova execução, essas linhas são ignoradas. |

A automação agrupa as linhas pelo par `Tipo Procuração` + documento representado. Antes de cada grupo, ela troca o perfil adequado e valida o documento informado. Linhas sem tipo, CNPJ de 14 dígitos para PJ ou CPF de 11 dígitos para PF são rejeitadas antes de abrir o eSocial.

Para cada trabalhador, ela abre exclusivamente o detalhe do agente `02.01.001 - Ruído` e lê a data de início e a intensidade exibidas. O relatório traz `data_planilha`, `data_esocial`, `data_confere`, `intensidade_planilha`, `intensidade_esocial` e `intensidade_confere` — `data_confere`/`intensidade_confere` só são preenchidos quando a planilha já trazia um valor esperado para conferência; caso contrário ficam em branco (não há divergência a checar). Nenhum dado é preenchido ou alterado no eSocial.

Além de `LOG` e `Status`, a automação também grava `Ano` e `Intensidade` na planilha de origem com os valores lidos no eSocial ao concluir cada linha (quando há agente de ruído identificado). Se ocorrer uma falha, o `Status` fica em branco: basta reenviar a mesma planilha para que a automação processe somente as linhas pendentes.
