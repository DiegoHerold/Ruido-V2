# Estratégia de testes

## Unitários

- normalização e máscara de CPF;
- contrato JSON de diagnóstico IA;
- manifesto somente leitura e campos obrigatórios;
- política que bloqueia semântica de transmissão/alteração.

## Integração controlada

Em uma máquina de homologação, usar uma planilha sintética e perfil Chrome separado para validar: abertura maximizada, identificação OCR do certificado autorizado, seleção de procuração, CPF encontrado/não encontrado, ausência de ruído e geração de artefatos.

## Regressão de segurança

Os testes não podem acionar eSocial real. O teste de contrato garante que o registry não introduz ação de escrita; qualquer novo seletor ou ação requer revisão humana antes de promoção.
