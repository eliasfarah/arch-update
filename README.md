# Central de atualizações do Arch

Interface GTK 4 / libadwaita em português para revisar pacotes e executar uma atualização completa do Arch Linux.

## Instalação

Requer Arch Linux com GNOME, Python 3, PyGObject, GTK 4, libadwaita e Polkit com agente de autenticação ativo na sessão.

Clone ou extraia o projeto e execute:

```sh
./install.sh
```

Depois, procure **Central de atualizações do Arch** no menu de aplicativos.

## Uso

- A lista mostra pacotes e versões comparando com a última base de repositórios salva localmente (`pacman -Qu`). A consulta não instala pacotes.
- A lista pode estar desatualizada. Antes da instalação, o pacman sincroniza as bases e executa uma atualização completa; podem surgir atualizações adicionais.
- O preview inclui repositórios configurados no pacman. Pacotes do AUR precisam ser atualizados separadamente pela ferramenta usada para instalá-los.
- A senha é solicitada pelo Polkit e não é armazenada pelo app.

O app mostra a saída da operação na seção **Detalhes**. Como a atualização é completa, mantenha o computador ligado até o processo terminar.
