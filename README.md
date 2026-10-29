# Central de atualizações do Arch

Interface GTK 4 / libadwaita em português para revisar pacotes e executar atualizações do Arch Linux com `yay`, incluindo pacotes do AUR.

## Instalação

Requer Arch Linux com GNOME Shell 51, `yay`, `sudo`, Python 3, PyGObject, GTK 4 e libadwaita.

Clone ou extraia o projeto e execute:

```sh
./install.sh
```

Depois, procure **Central de atualizações do Arch** no menu de aplicativos.
O instalador também ativa o indicador do GNOME. Ele consulta `yay -Qu` a cada 15 minutos, mostra uma notificação quando a lista de atualizações muda e abre a Central ao clicar no ícone da barra superior. Se o GNOME já estiver aberto e não reconhecer a extensão recém-instalada, ela fica marcada para ativação na próxima sessão.

## Uso

- A lista usa `yay -Qu` e inclui atualizações dos repositórios e do AUR. A consulta não instala pacotes.
- Os pacotes aparecem agrupados em Core, Extra, Multilib e AUR; repositórios personalizados ficam em Outros repositórios.
- A lista pode estar desatualizada. Ao instalar, o `yay -Syu` sincroniza os repositórios e pode encontrar atualizações adicionais.
- A senha é pedida em um diálogo da Central e enviada ao `sudo` por um canal local privado; ela não é gravada em arquivo nem exibida no registro.
- Ao clicar em **Instalar atualizações**, o yay usa `--noconfirm` para instalar tudo que encontrar após sincronizar, sem novas perguntas. A lista pode mudar desde a prévia mostrada.
- Com `--noconfirm`, o yay não abre a revisão interativa de diferenças dos pacotes do AUR. Confira os pacotes mostrados na Central antes de iniciar.
- Depois de uma atualização bem-sucedida, o contador da extensão é atualizado imediatamente.
- Ao terminar, clique em **Conferir atualizações** para atualizar a lista.

Como a atualização é completa, mantenha o computador ligado até o processo terminar.
