#!/usr/bin/python3
"""A small GTK 4 front end for complete Arch Linux system upgrades."""

import re
import shlex
import shutil
import subprocess
import threading
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk


APP_ID = "io.github.farah.archupdatecenter"


class UpdateCenter(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self.on_activate)
        self.packages = []
        self.busy = False
        self.awaiting_refresh = False

    def on_activate(self, _app):
        if hasattr(self, "window"):
            self.window.present()
            return
        self.window = Adw.ApplicationWindow(application=self, title="Atualizações do sistema")
        self.window.set_default_size(840, 720)
        self.window.set_size_request(580, 520)
        self.build_ui()
        self.window.present()
        self.refresh()

    def build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.set_content(root)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Atualizações", css_classes=["title"]))
        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Procurar atualizações")
        self.refresh_button.add_css_class("flat")
        self.refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_button)
        root.append(header)

        page = Adw.Clamp(maximum_size=900, tightening_threshold=620, vexpand=True)
        page.set_margin_top(22)
        page.set_margin_bottom(18)
        page.set_margin_start(26)
        page.set_margin_end(26)
        root.append(page)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, vexpand=True)
        page.set_child(content)

        title = Gtk.Label(label="Revise antes de instalar", xalign=0)
        title.add_css_class("title-1")
        subtitle = Gtk.Label(label="Confira os nomes e as versões que serão atualizadas.", xalign=0)
        subtitle.add_css_class("dim-label")
        subtitle.set_wrap(True)
        content.append(title)
        content.append(subtitle)

        self.summary = Adw.ActionRow(title="Procurando atualizações…", subtitle="A lista de pacotes aparecerá aqui")
        self.summary.set_icon_name("system-software-update-symbolic")
        card = Gtk.ListBox(css_classes=["boxed-list"])
        card.append(self.summary)
        content.append(card)

        self.notice = Adw.Banner(title="")
        self.notice.set_revealed(False)
        content.append(self.notice)

        section_head = Gtk.Box(spacing=8)
        section_title = Gtk.Label(label="Pacotes a atualizar", xalign=0, hexpand=True)
        section_title.add_css_class("heading")
        self.count = Gtk.Label(label="", css_classes=["dim-label", "caption"])
        section_head.append(section_title)
        section_head.append(self.count)
        content.append(section_head)

        self.search = Gtk.SearchEntry(placeholder_text="Buscar pacote pelo nome…")
        self.search.connect("search-changed", self.filter_packages)
        content.append(self.search)

        self.package_placeholder = Gtk.Label(label="Nenhuma atualização disponível", margin_top=24, margin_bottom=24)
        self.package_placeholder.add_css_class("dim-label")
        self.package_list = Gtk.ListBox()
        self.package_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.package_list.set_placeholder(self.package_placeholder)
        self.package_rows = []
        self.package_list.set_filter_func(self._filter_package_row)
        self.package_scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=180,
                                                   hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.package_scroller.add_css_class("card")
        self.package_scroller.set_child(self.package_list)
        content.append(self.package_scroller)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        bottom.set_margin_top(12)
        bottom.set_margin_bottom(18)
        bottom.set_margin_start(26)
        bottom.set_margin_end(26)
        self.bottom_label = Gtk.Label(label="", xalign=0, hexpand=True)
        self.bottom_label.add_css_class("dim-label")
        bottom.append(self.bottom_label)
        self.apply_button = Gtk.Button(label="Instalar atualizações", icon_name="software-update-available-symbolic")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.add_css_class("pill")
        self.apply_button.connect("clicked", self.on_primary_action)
        bottom.append(self.apply_button)
        root.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        root.append(bottom)

    def set_busy(self, busy):
        self.busy = busy
        self.refresh_button.set_sensitive(not busy)
        self.apply_button.set_sensitive(not busy)
        if busy:
            self.apply_button.set_label("Aguarde…")
        else:
            self.update_primary_button()

    def update_primary_button(self):
        if self.awaiting_refresh:
            label = "Conferir depois da atualização"
        elif len(self.packages) == 1:
            label = "Abrir terminal · 1 atualização"
        else:
            label = f"Abrir terminal · {len(self.packages)} atualizações" if self.packages else "Nada na lista"
        self.apply_button.set_label(label)
        self.bottom_label.set_label(
            f"{len(self.packages)} pacote" + ("s" if len(self.packages) != 1 else "")
            if self.packages else ""
        )

    def clear_packages(self):
        self.package_rows.clear()
        child = self.package_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.package_list.remove(child)
            child = nxt

    def _filter_package_row(self, row):
        query = self.search.get_text().strip().casefold()
        if not query:
            return True
        if getattr(row, "is_group_heading", False):
            return any(
                query in package_row.package_name.casefold()
                or query in package_row.package_source.casefold()
                for package_row in self.package_rows
                if package_row.package_group == row.package_group
            )
        return query in row.package_name.casefold() or query in row.package_source.casefold()

    def filter_packages(self, *_):
        query = self.search.get_text().strip()
        self.package_placeholder.set_text(
            "Nenhum pacote corresponde à busca" if query else "Nenhuma atualização disponível"
        )
        self.package_list.invalidate_filter()

    def set_notice(self, text="", warning=False):
        self.notice.set_title(text)
        self.notice.set_revealed(bool(text))
        if warning:
            self.notice.add_css_class("warning")
        else:
            self.notice.remove_css_class("warning")

    def refresh(self):
        if self.busy:
            return
        self.awaiting_refresh = False
        self.refresh_button.set_sensitive(True)
        self.set_busy(True)
        self.set_notice()
        self.summary.set_title("Procurando atualizações…")
        self.summary.set_subtitle("Consultando a lista de pacotes salva no computador")
        self.count.set_label("")
        self.search.set_text("")
        self.search.set_visible(False)
        self.clear_packages()
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        yay = shutil.which("yay")
        if not yay:
            GLib.idle_add(self._show_updates, [], "Yay não está instalado neste computador.", 1)
            return
        try:
            p = subprocess.run([yay, "-Qu"], capture_output=True, text=True, timeout=300)
            lines = (p.stdout or "").splitlines()
            entries = []
            pacman = shutil.which("pacman") or "pacman"
            foreign = subprocess.run([pacman, "-Qm"], capture_output=True, text=True, timeout=60)
            foreign_names = {line.split()[0] for line in foreign.stdout.splitlines() if line.split()}
            sync = subprocess.run([pacman, "-Sl"], capture_output=True, text=True, timeout=90)
            known_repositories = {"core": 0, "extra": 1, "multilib": 2}
            repository_by_package = {}
            for line in sync.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    repository, package_name = parts[0], parts[1]
                    if repository in known_repositories:
                        previous = repository_by_package.get(package_name)
                        previous_rank = known_repositories.get(previous, 99)
                        if previous is None or known_repositories[repository] < previous_rank:
                            repository_by_package[package_name] = repository
                    elif package_name not in repository_by_package:
                        repository_by_package[package_name] = repository
            for line in lines:
                m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)(?:\s+\[[^\]]+\])?$", line.strip())
                if m:
                    name, old, new = m.groups()
                    repository = repository_by_package.get(name)
                    if name in foreign_names or repository is None:
                        group, source = "aur", "AUR"
                    elif repository in known_repositories:
                        group, source = repository, repository.capitalize()
                    else:
                        group, source = "other", repository
                    entries.append((name, old, new, group, source))
            group_order = {"core": 0, "extra": 1, "multilib": 2, "aur": 3, "other": 4}
            entries.sort(key=lambda item: (group_order[item[3]], item[0].casefold()))
            err = (p.stderr or "").strip()
            if not entries and p.stdout.strip():
                err = p.stdout.strip()
            GLib.idle_add(self._show_updates, entries, err, p.returncode)
        except Exception as exc:
            GLib.idle_add(self._show_updates, [], str(exc), 1)

    def _show_updates(self, entries, err, code):
        self.set_busy(False)
        self.apply_button.set_label("Instalar atualizações")
        self.packages = entries
        self.clear_packages()
        current_group = None
        group_titles = {
            "core": "Core",
            "extra": "Extra",
            "multilib": "Multilib",
            "aur": "AUR",
            "other": "Outros repositórios",
        }
        for name, old, new, group, source in entries:
            if group != current_group:
                heading = Gtk.ListBoxRow()
                heading.set_selectable(False)
                heading.set_activatable(False)
                heading.is_group_heading = True
                heading.package_group = group
                heading_label = Gtk.Label(label=group_titles[group], xalign=0)
                heading_label.add_css_class("heading")
                heading_label.add_css_class("dim-label")
                heading_label.set_margin_top(12)
                heading_label.set_margin_bottom(4)
                heading_label.set_margin_start(16)
                heading_label.set_margin_end(16)
                heading.set_child(heading_label)
                self.package_list.append(heading)
                current_group = group
            row = Adw.ActionRow(title=name, subtitle=f"Versão atual  {old}    →    Nova versão  {new}")
            row.set_title_lines(1)
            row.set_subtitle_lines(2)
            row.set_subtitle_selectable(True)
            row.set_activatable(False)
            source_label = Gtk.Label(label=source)
            source_label.add_css_class("dim-label")
            source_label.add_css_class("caption")
            row.add_suffix(source_label)
            package_row = Gtk.ListBoxRow()
            package_row.set_selectable(False)
            package_row.set_activatable(False)
            package_row.package_name = name
            package_row.package_source = source.casefold()
            package_row.package_group = group
            package_row.set_child(row)
            self.package_list.append(package_row)
            self.package_rows.append(package_row)
        self.count.set_label((f"{len(entries)} pacote" if len(entries) == 1 else f"{len(entries)} pacotes") if entries else "")
        self.search.set_visible(bool(entries))
        if entries:
            self.summary.set_title(f"{len(entries)} atualizações disponíveis")
            self.summary.set_subtitle(f"Lista salva · consultada às {datetime.now().strftime('%H:%M')}")
            self.set_notice("A lista combina repositórios e AUR. Antes de instalar, yay atualiza a lista novamente.")
        elif not err and code in (0, 1, 2):
            self.summary.set_title("Nenhuma atualização na lista salva")
            self.summary.set_subtitle("A lista será sincronizada novamente antes de instalar")
        else:
            self.summary.set_title("Não foi possível procurar atualizações")
            self.summary.set_subtitle("Confira a conexão e tente novamente")
            self.set_notice(err or "Confira a conexão com a internet e tente novamente.", True)
        self.apply_button.set_sensitive(bool(entries))
        self.update_primary_button()
        return GLib.SOURCE_REMOVE

    def confirm_update(self, *_):
        if self.busy or not self.packages:
            return
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading="Instalar as atualizações?",
            body=f"A consulta encontrou {len(self.packages)} atualizações entre repositórios e AUR. O yay será aberto no Terminal. Digite sua senha e responda às perguntas do yay nessa janela. Mantenha o computador ligado até terminar.",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("update", "Instalar atualizações")
        dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("update")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._begin_update)
        dialog.present()

    def on_primary_action(self, *_):
        if self.awaiting_refresh:
            self.refresh()
        else:
            self.confirm_update()

    def _begin_update(self, dialog, response):
        dialog.close()
        if response != "update":
            return
        yay = shutil.which("yay")
        terminal = shutil.which("kgx") or shutil.which("gnome-terminal") or shutil.which("konsole") or shutil.which("xterm")
        if not yay or not terminal:
            self.set_notice("Preciso encontrar yay e um aplicativo de Terminal para continuar.", True)
            return
        try:
            script = (
                f"{shlex.quote(yay)} -Syu; result=$?; printf '\\n'; "
                "if [ \"$result\" -eq 0 ]; then printf 'Atualização concluída.\\n'; "
                "else printf 'O yay terminou com código %s.\\n' \"$result\"; fi; "
                "read -r -p 'Pressione Enter para fechar esta janela… ' _"
            )
            if terminal.endswith("kgx") or terminal.endswith("gnome-terminal"):
                command = [terminal, "--", "/bin/bash", "-lc", script]
            elif terminal.endswith("konsole"):
                command = [terminal, "-e", "/bin/bash", "-lc", script]
            else:
                command = [terminal, "-e", "/bin/bash", "-lc", script]
            subprocess.Popen(command, start_new_session=True, close_fds=True)
        except Exception as exc:
            self.set_notice(f"Não consegui abrir o Terminal: {exc}", True)
            return
        self.awaiting_refresh = True
        self.refresh_button.set_sensitive(False)
        self.summary.set_title("Atualização aberta no Terminal")
        self.summary.set_subtitle("Responda às perguntas por lá. Volte aqui quando terminar.")
        self.set_notice("A senha será solicitada pelo yay no Terminal; o aplicativo não a recebe.")
        self.update_primary_button()
        return GLib.SOURCE_REMOVE


if __name__ == "__main__":
    UpdateCenter().run()
