# Como rodar pelo terminal

Abra o PowerShell nesta pasta do projeto:

```powershell
cd "C:\Users\diego\Desktop\Projetos\Self-healing-automation\Ruido V2"
```

Na primeira vez, instale as dependencias:

```powershell
.\run.ps1 -InstallDeps
```

Depois execute tudo usando as pastas configuradas no `.env`:

```powershell
.\run.ps1
```

## Login manual no perfil de automacao

Quando `MANUAL_LOGIN_BEFORE_RUN=true`, a automacao fecha todas as sessoes do Chrome e abre o eSocial com `CHROME_DEBUG_USER_DATA_DIR=C:/tmp/chrome-debug-esocial`.

Esse perfil separado permite a porta de controle `CHROME_REMOTE_DEBUGGING_PORT=9222`, como no teste manual que funcionou.

A janela nao e forçada a maximizar, porque isso estava causando conflito visual com o Chrome/Redtrust.

Antes de pedir o login manual, a automacao testa a porta `CHROME_REMOTE_DEBUGGING_PORT`.
Se essa porta nao abrir, o robo para antes do login, porque nao conseguiria continuar na mesma janela.

Nesse momento o robo nao tenta clicar certificado, nao usa OCR e nao mexe no CAPTCHA. Na primeira vez, se a Redtrust nao aparecer nesse perfil, instale/configure a extensao nele.

Faça manualmente:

1. login no eSocial;
2. certificado/Redtrust/CAPTCHA, se aparecer;
3. perfil/procuracao correta, se necessario.

Quando estiver dentro do eSocial, volte ao terminal e pressione ENTER.

Depois disso ela conecta nessa mesma janela e executa a consulta SST automaticamente, sem fechar/reabrir e sem copiar perfil.

Para testar sem abrir o eSocial:

```powershell
.\run.ps1 -Test
```

Para executar uma planilha especifica:

```powershell
.\run.ps1 -InputFile "C:\caminho\arquivo.xlsx"
```

Tambem funciona pelo Prompt de Comando:

```cmd
run.cmd
```

## Problema atual encontrado

Neste Windows, `python` e `py` nao estao no PATH, e o `.venv` existente aponta para:

```text
C:\Users\diego\AppData\Local\Programs\Python\Python314\python.exe
```

Esse Python nao esta acessivel. Instale Python 3.11 ou 3.12 marcando `Add python.exe to PATH`, abra um terminal novo e rode:

```powershell
.\run.ps1 -InstallDeps
.\run.ps1
```
