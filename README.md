# Central de atualizações do Arch

Interface GTK 4 / libadwaita em português para revisar pacotes e executar atualizações do Arch Linux com `yay`, incluindo pacotes do AUR.

## Instalação

Requer Arch Linux com GNOME Shell 51, `yay`, `sudo`, `fakeroot`, Python 3, PyGObject, GTK 4 e libadwaita.

Clone ou extraia o projeto e execute:

```sh
./install.sh
```

Depois, procure **Central de atualizações do Arch** no menu de aplicativos.
O instalador também ativa o indicador do GNOME. Ele atualiza a consulta segura a cada 15 minutos, mostra uma notificação quando a lista de atualizações muda e abre a Central ao clicar no ícone da barra superior. Se o GNOME não reconhecer uma extensão recém-instalada, ela fica marcada para ativação na próxima sessão.

Ao abrir a Central novamente pelo indicador, a lista é consultada outra vez.

## Uso

- A lista sincroniza bases temporárias dos repositórios, sem alterar a base real do pacman, e consulta o AUR separadamente. A consulta não instala pacotes.
- Os pacotes aparecem agrupados em Core, Extra, Multilib e AUR; repositórios personalizados ficam em Outros repositórios.
- Ao instalar, o `yay -Syyu` força outra sincronização e pode encontrar atualizações que chegaram depois da prévia.
- A senha é pedida em um diálogo da Central e enviada ao `sudo` por um canal local privado; ela não é gravada em arquivo nem exibida no registro.
- Durante a instalação, a Central mostra o andamento por pacote e marca os concluídos; a saída detalhada do terminal fica recolhida em **Ver terminal**.
- Ao clicar em **Instalar atualizações**, o yay usa `--noconfirm` e desativa menus de limpeza, diffs e edição, mesmo que estejam ligados na configuração do usuário. Instala tudo que encontrar após sincronizar; a lista pode mudar desde a prévia.
- Com `--noconfirm`, o yay não abre a revisão interativa de diferenças dos pacotes do AUR. Confira os pacotes mostrados na Central antes de iniciar.
- Depois de uma atualização bem-sucedida, o contador da extensão é atualizado imediatamente.
- Ao terminar, clique em **Conferir atualizações** para atualizar a lista.

Como a atualização é completa, mantenha o computador ligado até o processo terminar.
