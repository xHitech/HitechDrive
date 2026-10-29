# Divulgação do HitechDrive

Textos preparados para adaptação e publicação pelo mantenedor. Nenhuma postagem é enviada automaticamente. Confira as regras de cada comunidade antes de divulgar.

## Apresentação curta em português

Criei o HitechDrive para manter uma cópia local do Google Drive no Linux e usar meus arquivos com o Jellyfin. Tem painel visual, downloads retomáveis, controle de banda, temas claro/escuro e acompanhamento dos discos. Usa Python e JavaScript, sem Docker nem rclone.

Está em versão experimental e eu queria feedback de quem usa Linux e servidor de mídia. A sincronização é de uma direção: Drive → disco. O código é MIT, e tem uma demonstração offline com dados fictícios para conhecer a interface antes de configurar o Google.

Código e instruções: https://github.com/xHitech/HitechDrive

## Short introduction in English

I built HitechDrive to keep a local Google Drive library on Linux and make it available to Jellyfin. It has a visual dashboard, resumable downloads, a shared bandwidth limit, light/dark themes and disk activity diagnostics. Python standard library + vanilla JavaScript; no Docker or rclone required.

This is an experimental, one-way Drive-to-disk client. The UI is currently in Portuguese and real synchronization requires your own Google Desktop OAuth credentials. The MIT-licensed repository includes an offline demo with fictional data. I'd appreciate reproducible bug reports and feedback from Linux and home-server users.

Code and setup: https://github.com/xHitech/HitechDrive

## Materiais

- `docs/assets/social-preview.png`: capa de compartilhamento (1280 × 640).
- `docs/assets/preview.gif`: animação ilustrativa com dados fictícios.
- `docs/assets/preview-light.png` e `preview-dark.png`: prévias ilustrativas dos temas.
- `docs/demo.html`: demonstração offline da interface real em português.

A capa de compartilhamento do GitHub precisa ser carregada em **Settings → General → Social preview**. Use `social-preview.png`. O script de lançamento configura descrição e tópicos, mas não faz esse upload.

## Um lançamento pequeno, depois feedback

1. Execute `bash tools/lancar-github.sh` para publicar o código, configurar os tópicos e criar a versão experimental. A demo HTML e a capa ficam disponíveis como anexos da versão. Confira o README como visitante.
2. Mostre a demonstração em uma comunidade adequada e peça feedback específico sobre instalação e clareza do painel.
3. Corrija os problemas reproduzidos antes de ampliar a divulgação.
4. Mostre melhorias concretas nas próximas versões. Não compre estrelas nem envie divulgação em massa.

Não prometa velocidades fixas, suporte completo ao Drive ou ausência de falhas. As prévias não demonstram desempenho medido. Antes de trocar por capturas reais, retire nomes de arquivos, contas e informações do ambiente.
