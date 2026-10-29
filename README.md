# HitechDrive

Seu Google Drive, com uma cópia de verdade no seu Linux.

Cliente independente com painel local, downloads paralelos, retomada de transferências, limite de banda compartilhado e diagnóstico dos discos e da conexão. Feito com Python e JavaScript, sem rclone, Docker ou dependências Python externas.

**Um projeto [Hitech Studio · xHitech](https://github.com/xHitech).** Não é um produto oficial do Google. Projeto em desenvolvimento para uso pessoal; leia os limites abaixo antes de usar com arquivos importantes.

## O que tem

- Interface em português com temas claro/escuro, escolha salva no navegador e preferência inicial do sistema.
- Visão geral do acervo, downloads ativos, previsão aproximada e progresso individual.
- De 1 a 8 downloads simultâneos, ajustáveis durante a sincronização.
- Limite total de velocidade em MiB/s. `0` significa sem limite.
- Download binário retomável com HTTP Range, tamanho, MD5 quando fornecido e conferência de versão remota.
- Catálogo inicial paginado e atualizações pelo histórico incremental da API do Drive.
- Erros persistentes, retentativas e lixeira local para arquivos removidos/substituídos.
- Métricas passivas de RAID10, discos, rede e etapas do download, sem executar benchmark.
- Renomeações e movimentações por ID do Drive, reaproveitando conteúdo local validado por checksum.
- Recuperação de manifesto, reconhecimento de arquivos existentes e auditoria opcional com limite de leitura.
- Prévia de limpeza de lixeira/parciais e alertas de autenticação, espaço, volume e RAID degradado.
- OAuth desktop com PKCE e acesso somente de leitura na nuvem.

## Requisitos

- Linux com Python 3.11 ou superior.
- `findmnt` (normalmente fornecido por util-linux).
- Volume de destino já montado, identificável por UUID e com permissões de escrita para seu usuário.
- Navegador moderno. systemd de usuário é opcional para executar em segundo plano.
- Um aplicativo OAuth pessoal com Google Drive API habilitada.

O programa não cria RAID, não monta volumes e não formata discos. Também pode copiar para um volume comum: o RAID não é obrigatório; os gráficos de RAID10 só aparecem quando esse tipo de conjunto está presente.

## Instalar e configurar

```bash
git clone https://github.com/xHitech/HitechDrive.git
cd HitechDrive
```

Configure um volume **já montado**, usando o ponto correto do seu computador. Neste exemplo, `/mnt/media` é apenas um caminho ilustrativo:

```bash
python configurar-volume.py --mountpoint /mnt/media
```

O destino padrão será a subpasta `GoogleDrive` nesse volume. Para escolher outra subpasta:

```bash
python configurar-volume.py --mountpoint /mnt/media --destination /mnt/media/MinhaReplica
```

O UUID e os caminhos ficam em um arquivo privado `instance.json` dentro de `~/.local/share/drive-espelho`. Antes de escrever, o programa confirma que o volume esperado continua montado e que o destino permanece dentro dele. **Não salva sua configuração no código-fonte.** Se já houver uma réplica registrada, a troca de volume é bloqueada para preservar os arquivos.

Execute como usuário normal, **sem sudo**:

```bash
bash iniciar.sh
```

Abra **http://127.0.0.1:8765** no navegador. Em Configurações, conecte a conta e escolha a origem. Use `root` para o Meu Drive, ou o ID/link de uma pasta.

## Autorizar sua conta Google

1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/).
2. Ative **Google Drive API** na biblioteca de APIs.
3. Configure o Google Auth Platform. Em modo de teste, adicione seu e-mail aos usuários de teste.
4. Crie um cliente OAuth do tipo **Aplicativo para computador / Desktop app**.
5. Baixe o JSON, importe-o em **Configurações** no HitechDrive e clique em conectar.
6. Autorize a leitura do Drive pelo navegador.

Não use chave de API ou conta de serviço para esse fluxo. Não publique JSON OAuth, tokens ou arquivos da sua conta. Endereços OAuth são fixos do Google; o aplicativo não usa endpoints arbitrários recebidos no JSON.

Em apps externos no modo Testing, o Google pode expirar a autorização offline após sete dias. Consulte o Google Auth Platform e as [regras de expiração](https://developers.google.com/identity/protocols/oauth2#expiration) para configurar o uso pessoal contínuo. Publicar o consentimento não torna o app automaticamente verificado nem elimina as políticas de escopos restritos.

## Painel

- **Visão geral:** progresso do acervo, total dos downloads atuais, arquivos individuais e ajustes rápidos.
- **Desempenho:** gráficos dos discos e da conexão, filas, latência e possíveis gargalos.
- **Pendências:** motivo das falhas, tentativas e ação para tentar novamente.
- **Atividade:** últimos eventos da sessão.
- **Manutenção:** recuperação, auditoria e limpeza revisada, com a sincronização pausada.
- **Configurações:** conta, pasta de origem e intervalo de atualização.

O botão de lua/sol na barra superior troca o tema. A preferência é salva somente no navegador; não altera sua conta ou seus arquivos.

Alterar o número de downloads aplica automaticamente o novo limite. Ao reduzir, os já iniciados terminam; novas vagas aguardam o limite. A banda é dividida entre todos os downloads, e aceita valores decimais. Limitar leituras do aplicativo não controla buffers do sistema, consultas de metadados ou tráfego de outros programas.

## Serviço opcional

```bash
bash instalar-servico.sh
```

```bash
systemctl --user status drive-espelho
journalctl --user -u drive-espelho -f
systemctl --user restart drive-espelho
systemctl --user stop drive-espelho
```

Para continuar ativo após sair da sessão, se desejado:

```bash
sudo loginctl enable-linger "$USER"
```

O serviço inicia com sua sessão. Ativo/pausado permanece salvo nas reinicializações. Execute apenas uma instância por diretório de estado.

## Acessar de outro computador

O painel escuta apenas em loopback. Use um túnel SSH a partir do computador onde está o navegador, substituindo `usuario@servidor` pelo seu acesso:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8765:127.0.0.1:8765 usuario@servidor
```

Mantenha o terminal aberto e abra http://127.0.0.1:8765 nesse computador. O callback OAuth também passa pelo túnel. Não exponha diretamente a porta na internet.

## Dados privados e reinstalações

O estado padrão é `~/.local/share/drive-espelho`, com diretório 0700 e JSONs 0600. Inclui configuração local, conta, tokens, catálogo, manifesto e erros. Esses dados não fazem parte do repositório e são ignorados pelo Git.

Em **Manutenção**, pause a sincronização e espere os downloads terminarem. Exporte o backup de recuperação e guarde-o fora do computador antes de reinstalar. Ele contém manifesto, identificação da conta, caminhos e UUID do volume; **não contém tokens nem segredo OAuth**, mas é privado por conter nomes de arquivos.

A cada ciclo concluído, o aplicativo também grava um checkpoint privado em `.drive-espelho/recovery.json` dentro do destino. Depois de reinstalar, configure o mesmo volume e destino, pause o aplicativo e importe o backup ou restaure o checkpoint pelo painel. A importação exige manifesto vazio e o mesmo UUID; a conta da réplica fica vinculada à recuperação. Importe novamente seu JSON OAuth e reconecte a mesma conta, se necessário.

Sem backup, **Reconhecer arquivos existentes** consulta o Drive e lê os arquivos locais para adotar apenas os que coincidem em tamanho e MD5 remoto. Não baixa nem sobrescreve conteúdo. Formatos sem checksum remoto são ignorados. Essa recuperação completa pode demorar; use o limite de leitura e o cancelamento.

Não apague o estado para forçar troca de conta/origem sobre a mesma réplica.

O destino usa arquivos legíveis por outros usuários locais para facilitar o uso com servidores de mídia. Se essa não for sua intenção, revise as permissões no seu ambiente.

## Limites e comportamento de preservação

- Uma direção: **Drive → disco**. Não envia alterações nem exclui arquivos no Google.
- A origem fica fixa depois de haver arquivos registrados. A troca de conta também é bloqueada para preservar a réplica.
- Exclusões locais são adiadas até a listagem completa e os downloads do ciclo concluírem. São movimentações para `.drive-espelho/lixeira`, sem descarte permanente automático.
- A lixeira e parciais de versões antigas ocupam espaço. Em Manutenção, gere a prévia, revise os arquivos, escolha a categoria e digite a confirmação de exclusão permanente. Arquivos alterados depois da prévia são preservados; não há limpeza automática.
- Conteúdo local modificado não é enviado ao Drive. Ao substituir, a cópia anterior é preservada na lixeira. Não use a réplica como origem de edição bidirecional.
- O aplicativo não remove arquivos locais desconhecidos fora do manifesto. Use uma pasta dedicada.
- Docs → DOCX, Sheets → XLSX, Slides → PPTX e Drawings → PDF. São exportações; outros formatos nativos e atalhos viram arquivos `.url`.
- Exportações têm limites da API e não oferecem a mesma retomada por Range dos binários. Respostas com tamanho anunciado incompleto são rejeitadas.
- Não inclui automaticamente “Compartilhados comigo”, histórico de versões, permissões, comentários, lixeira remota ou unidades compartilhadas.
- Nomes incompatíveis e duplicados são adaptados. Uma réplica integral, idêntica ao serviço Google Drive não é possível.
- Renomear/mover no Drive conserva o ID. Com tamanho e checksum iguais e metadados locais intactos, o arquivo é movido no disco sem novo download. Um diário permite retomar movimentações interrompidas. Conteúdo alterado ou sem evidência suficiente segue a atualização conservadora. O manifesto completo ainda é gravado após cada conclusão; acervos muito grandes podem gerar custo extra.
- O hash é conferido ao terminar downloads. Arquivos já concluídos não são relidos inteiros em cada ciclo: são comparados metadados, tamanho e data locais.
- Os contadores incluem parciais. 100% dos bytes recebidos pode aparecer antes da validação final. Documentos sem tamanho conhecido ficam fora do total em bytes.
- A pausa acontece entre operações; chamadas de rede podem demorar até o timeout. A fila aguarda os workers drenarem antes de outro ciclo.

## Auditoria e alertas

A auditoria é opcional: lê o conteúdo e compara com o MD5 registrado, sem corrigir, apagar ou baixar arquivos. Exige sincronização pausada, usa por padrão 8 MiB/s e aceita `0` para leitura ilimitada. Pode ser cancelada; o relatório mostra contagens e até 100 ocorrências. Não é executada automaticamente a cada ciclo.

O painel alerta sobre autorização expirada, volume indisponível, pouco espaço, RAID degradado e falhas da auditoria/checkpoint. São verificações locais; não substituem monitoramento SMART ou backup independente. A manutenção bloqueia sincronização e alterações de configuração enquanto está ativa.

## Interpretar o diagnóstico

100% de ocupação de HD significa tempo com I/O em andamento, não velocidade nominal máxima. Filas e latências elevadas em várias amostras são indícios de limitação; não provam defeito físico ou substituem SMART.

O percentual da internet usa o plano que você informar como referência. O tráfego da placa inclui LAN e outros aplicativos. Não mede capacidade interna do Google nem distingue, sozinho, gargalo do provedor remoto e da rota. A distribuição de tempos dos workers também não equivale a porcentagem de utilização de serviços externos.

## Desenvolvimento e validação

```bash
python -m unittest -v
node --check static/ui.js
node --check static/diagnostics.js
node --check static/theme.js
node --check static/maintenance.js
bash -n iniciar.sh instalar-servico.sh
```

Testes usam diretórios temporários e respostas simuladas. Não acessam uma conta Google nem seu volume real. A autorização, comportamento na sua rede e inspeção visual em navegador precisam de validação no ambiente de uso.

## Referências oficiais

- [OAuth desktop](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Downloads e exportações](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Histórico de alterações](https://developers.google.com/workspace/drive/api/guides/manage-changes)
- [Estatísticas de I/O do Linux](https://docs.kernel.org/admin-guide/iostats.html)
