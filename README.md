# Central de atualizações do Arch

Interface GTK 4 / libadwaita em português para revisar pacotes e executar atualizações do Arch Linux com `yay`, incluindo pacotes do AUR.

## Instalação

Requer Arch Linux com GNOME, `yay`, Python 3, PyGObject, GTK 4, libadwaita e um terminal gráfico (GNOME Console/`kgx` recomendado).

Clone ou extraia o projeto e execute:

```sh
./install.sh
```

Depois, procure **Central de atualizações do Arch** no menu de aplicativos.

## Uso

- A lista usa `yay -Qu` e inclui atualizações dos repositórios e do AUR. A consulta não instala pacotes.
- A lista pode estar desatualizada. Antes de instalar, clique em **Abrir terminal**; o app abre `yay -Syu` para sincronizar os repositórios e revisar as perguntas do yay.
- Digite a senha e responda às perguntas do yay no Terminal. O aplicativo não recebe nem guarda a senha.
- Ao terminar, volte ao app e clique em **Conferir depois da atualização** para atualizar a lista.

O Terminal mostra a saída da operação e as perguntas do yay. Como a atualização é completa, mantenha o computador ligado até o processo terminar.
