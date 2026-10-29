# Changelog

## Em desenvolvimento

- Executa o yay na Central, com diálogo de senha e respostas às perguntas na própria janela.
- Corrige a extensão para os componentes de barra do GNOME Shell 51.

## 0.3.0

- Adiciona extensão GNOME para consultar yay periodicamente e notificar quando encontrar atualizações.
- O ícone da barra superior abre diretamente a Central de atualizações.
- O instalador instala e ativa a extensão para o usuário atual.
- Agrupa os pacotes na Central por Core, Extra, Multilib e AUR.

## 0.2.0

- Usa `yay -Qu` para mostrar atualizações de repositórios e AUR.
- Executa `yay -Syu` em um terminal interativo, para que senha, revisão de PKGBUILDs e confirmações permaneçam visíveis.
- Permite conferir novamente a lista depois da atualização.

## 0.1.0

- Primeira versão da interface GTK 4 / libadwaita em português.
- Lista pacotes atualizáveis dos repositórios configurados usando a base local do pacman.
- Permite buscar pacotes e revisar as versões antes da atualização completa.
- Executa `pacman -Syu` com autenticação Polkit e mostra o registro da operação.
- Inclui ícone vetorial e instalador por usuário.
