# Operação e homologação

1. Copie `.env.example` para `.env`. No fluxo de autenticação do eSocial não é necessária chave de IA: `AI_DIAGNOSIS_ENABLED=false` e `ai_diagnosis_enabled: false` são os padrões.
2. Instale Python 3.11+, Google Chrome, Tesseract OCR (idioma `por`) e as dependências: `pip install -r requirements.txt`.
2. Instale o navegador suportado: `playwright install chrome`.
3. Caso o Tesseract não esteja no `PATH`, configure `TESSERACT_CMD` com o caminho completo do executável.
4. Regra obrigatória de reinício: antes de toda nova tentativa, a automação encerra todas as instâncias do Chrome, espera até 10 segundos pela confirmação e só então abre o último perfil. Isso impede o reaproveitamento da sessão anterior do eSocial.
5. No `.env`, defina `INPUT_FOLDER` e `RESULTS_FOLDER`. Sem `--input`, a execução processa em ordem alfabética todas as planilhas da pasta de entrada, fecha todas as instâncias do Chrome entre uma planilha e outra e cria uma subpasta de relatório para cada arquivo em `RESULTS_FOLDER`.
6. Preencha a planilha a partir de `examples/input-template.xlsx`; o modelo corresponde às colunas de `bibi.xlsx`.
7. Ajuste os seletores em `selectors.json` apenas depois de uma homologação. Mudanças só podem ser candidatas validadas e auditadas.
8. Rode `python -m pytest` e depois `python run.py`. Para processar um único arquivo, use `python run.py --input "C:/caminho/arquivo.xlsx"`.

O login é direto e determinístico: após encerrar todas as instâncias do Chrome, abrir `https://www.gov.br/esocial/pt-br` (minúsculas), clicar `Acesse`, usar DOM para `Entrar com gov.br` e `Seu certificado digital`, OCR local somente para `BIASON CONTABILIDADE` e `OK`, e validar a tela autenticada. Nenhuma chamada de IA integra esse caminho. Não execute contra produção até validar login, certificado, seleção de procuração e uma planilha de homologação. Captcha, MFA, janela OCR ambígua, divergência de CPF/CNPJ ou qualquer semântica de escrita exigem revisão humana.
## Renovação da sessão

O eSocial pode apresentar, aproximadamente a cada 20 minutos, o modal `Atenção!` com o texto `Sua sessão vai expirar em breve`. A automação reconhece apenas esse texto e clica uma única vez em `SIM`; em seguida comprova que o modal desapareceu antes de continuar.

Se o texto, o botão ou o fechamento do modal não forem comprovados, ela para em segurança. O arquivo `employee-state.json` já contém cada CPF finalizado; a retomada deve fechar todas as instâncias do Chrome, autenticar novamente e iniciar pela primeira linha ainda não registrada.
