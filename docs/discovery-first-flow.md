# Fluxo determinístico de autenticação no eSocial

Fluxo validado em 2026-09-08. Ele não usa IA, visão generativa, coordenadas fixas nem tentativa ilimitada.

1. Encerrar todas as instâncias do Chrome e confirmar que nenhum processo `chrome.exe` permaneceu ativo.
2. Abrir `https://www.gov.br/esocial/pt-br` em Chrome interativo, maximizado e usando o último perfil local. A URL deve permanecer em minúsculas.
3. Localizar pelo DOM o botão `Acesse` e clicar.
4. Localizar pelo DOM o botão `Entrar com gov.br` e clicar.
5. Esperar até 1 segundo. Se o eSocial já estiver autenticado, validar simultaneamente `Titular do Certificado` e `SAIR`, registrar `direct_authenticated_return` e seguir.
6. Caso contrário, localizar pelo DOM o botão `Seu certificado digital` e clicar.
7. Esperar no máximo 45 segundos pelo seletor nativo do Windows. Usar OCR local para localizar uma única linha que contenha `BIASON CONTABILIDADE`; clicar no centro da caixa OCR encontrada.
8. Capturar nova evidência. Usar OCR local para localizar uma única ocorrência do botão `OK`; clicar no centro da caixa OCR encontrada.
9. Esperar no máximo 25 segundos pelo retorno. Só considerar sucesso quando a página do eSocial tiver `Titular do Certificado` e `SAIR`.

Se qualquer texto estiver ausente ou ambíguo, a janela não puder ser comprovada como seletor de certificado, aparecer captcha/MFA, ou o retorno ao eSocial não for provado, o fluxo para com `human_review_required`. Não há fallback com IA, escolha de outro certificado, clique por coordenada fixa ou nova tentativa automática.

Uma tentativa anterior retornou `ERR_SSL_CLIENT_AUTH_SIGNATURE_FAILED`. Essa falha pertence à assinatura/autenticação do certificado; o script deve registrar a evidência e parar para revisão humana. Ele não deve escolher outro certificado, repetir indefinidamente ou tentar contornar a autenticação.

## Continuidade por CNPJ

Depois de abrir o detalhe do agente `02.01.001 - Ruído` e registrar a comparação, a automação verifica a linha seguinte da planilha. Se ela tiver o mesmo `Perfil` e o mesmo CNPJ representado, retorna diretamente para `https://frontend.esocial.gov.br/sst/gestaoTrabalhadores` e busca o próximo CPF. Ela não fecha o Chrome, não refaz o login e não troca perfil nesse caso. Quando o CNPJ mudar, o retorno direto não é usado: o contexto de procuração deverá ser validado novamente antes da próxima consulta.
