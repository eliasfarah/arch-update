#!/usr/bin/python3
"""A small GTK 4 front end for complete Arch Linux system upgrades."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
from update_backend import UpdateSession


APP_ID = "io.github.farah.archupdatecenter"


class UpdateCenter(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self.on_activate)
        self.packages = []
        self.busy = False
        self.query_ok = False
        self.awaiting_refresh = False
        self.operation_active = False
        self.session = None
        self.password_dialog = None
        self.password_request = None
        self.prompt_tail = ""
        self.response_secret = False

    def on_activate(self, _app):
        if hasattr(self, "window"):
            self.window.present()
            return
        self.window = Adw.ApplicationWindow(application=self, title="Atualizações do sistema")
        self.window.set_default_size(840, 720)
        self.window.set_size_request(580, 520)
        self.window.connect("close-request", self._on_close_request)
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

        self.page_title = Gtk.Label(label="Revise antes de instalar", xalign=0)
        self.page_title.add_css_class("title-1")
        self.page_subtitle = Gtk.Label(label="Confira os nomes e as versões que serão atualizadas.", xalign=0)
        self.page_subtitle.add_css_class("dim-label")
        self.page_subtitle.set_wrap(True)
        content.append(self.page_title)
        content.append(self.page_subtitle)

        self.summary = Adw.ActionRow(title="Procurando atualizações…", subtitle="A lista de pacotes aparecerá aqui")
        self.summary.set_icon_name("system-software-update-symbolic")
        card = Gtk.ListBox(css_classes=["boxed-list"])
        card.append(self.summary)
        content.append(card)

        self.notice = Adw.Banner(title="")
        self.notice.set_revealed(False)
        content.append(self.notice)

        self.pages = Gtk.Stack(vexpand=True)
        self.pages.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        content.append(self.pages)
        self.package_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, vexpand=True)
        self.pages.add_named(self.package_page, "packages")

        section_head = Gtk.Box(spacing=8)
        section_title = Gtk.Label(label="Pacotes a atualizar", xalign=0, hexpand=True)
        section_title.add_css_class("heading")
        self.count = Gtk.Label(label="", css_classes=["dim-label", "caption"])
        section_head.append(section_title)
        section_head.append(self.count)
        self.package_page.append(section_head)

        self.search = Gtk.SearchEntry(placeholder_text="Buscar pacote pelo nome…")
        self.search.connect("search-changed", self.filter_packages)
        self.package_page.append(self.search)

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
        self.package_page.append(self.package_scroller)

        self.operation_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, vexpand=True)
        self.pages.add_named(self.operation_page, "operation")
        operation_header = Gtk.Box(spacing=10)
        self.operation_spinner = Gtk.Spinner()
        operation_header.append(self.operation_spinner)
        self.operation_label = Gtk.Label(label="Preparando a atualização…", xalign=0, hexpand=True)
        self.operation_label.add_css_class("heading")
        operation_header.append(self.operation_label)
        self.respond_button = Gtk.Button(label="Responder pergunta")
        self.respond_button.connect("clicked", self._show_response_controls)
        operation_header.append(self.respond_button)
        self.operation_page.append(operation_header)

        self.operation_log = Gtk.TextView(editable=False, cursor_visible=False,
                                         wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True,
                                         top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        log_scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=160,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER)
        log_scroller.add_css_class("card")
        log_scroller.set_child(self.operation_log)
        self.operation_page.append(log_scroller)

        self.response_revealer = Gtk.Revealer(reveal_child=False)
        response_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.response_hint = Gtk.Label(label="Responda à pergunta acima. A senha será pedida em um diálogo da Central.", xalign=0)
        self.response_hint.set_wrap(True)
        self.response_hint.add_css_class("dim-label")
        response_box.append(self.response_hint)
        response_buttons = Gtk.Box(spacing=8)
        for label, value in (("Sim", "y"), ("Não", "n"), ("Continuar", "")):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _button, answer=value: self._send_response(answer))
            response_buttons.append(button)
        response_box.append(response_buttons)
        response_entry_row = Gtk.Box(spacing=8)
        self.response_entry = Gtk.Entry(placeholder_text="Outra resposta", hexpand=True)
        self.response_entry.connect("activate", lambda *_: self._send_response(self.response_entry.get_text()))
        response_entry_row.append(self.response_entry)
        send_button = Gtk.Button(label="Enviar")
        send_button.connect("clicked", lambda *_: self._send_response(self.response_entry.get_text()))
        response_entry_row.append(send_button)
        response_box.append(response_entry_row)
        self.response_revealer.set_child(response_box)
        self.operation_page.append(self.response_revealer)

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
            label = "Conferir atualizações"
        elif len(self.packages) == 1:
            label = "Instalar 1 atualização"
        else:
            label = f"Instalar {len(self.packages)} atualizações" if self.packages else "Verificar e atualizar"
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
        self.query_ok = False
        self.pages.set_visible_child_name("packages")
        self.page_title.set_label("Revise antes de instalar")
        self.page_subtitle.set_label("Confira os nomes e as versões que serão atualizadas.")
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
        self.query_ok = bool(entries) or (not err and code in (0, 1, 2))
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
            row.set_selectable(False)
            row.package_name = name
            row.package_source = source.casefold()
            row.package_group = group
            self.package_list.append(row)
            self.package_rows.append(row)
        self.count.set_label((f"{len(entries)} pacote" if len(entries) == 1 else f"{len(entries)} pacotes") if entries else "")
        self.search.set_visible(bool(entries))
        if entries:
            self.summary.set_title(f"{len(entries)} atualizações disponíveis")
            self.summary.set_subtitle(f"Lista salva · consultada às {datetime.now().strftime('%H:%M')}")
            self.set_notice("Ao clicar em Instalar, yay sincroniza e instala tudo que encontrar, sem outra confirmação. A lista pode mudar desde esta prévia.")
        elif not err and code in (0, 1, 2):
            self.summary.set_title("Nenhuma atualização na lista salva")
            self.summary.set_subtitle("A lista será sincronizada novamente antes de instalar")
            self.set_notice("Clique em Verificar e atualizar para sincronizar e instalar automaticamente qualquer atualização encontrada.")
        else:
            self.summary.set_title("Não foi possível procurar atualizações")
            self.summary.set_subtitle("Confira a conexão e tente novamente")
            self.set_notice(err or "Confira a conexão com a internet e tente novamente.", True)
        self.apply_button.set_sensitive(self.query_ok)
        self.update_primary_button()
        return GLib.SOURCE_REMOVE

    def on_primary_action(self, *_):
        if self.awaiting_refresh:
            self.refresh()
        else:
            self._begin_update()

    def _begin_update(self):
        if self.busy or not self.query_ok:
            return
        yay = shutil.which("yay")
        sudo = shutil.which("sudo")
        if not yay or not sudo:
            self.set_notice("Preciso encontrar yay e sudo para continuar.", True)
            return

        command = [yay, "-Syu", "--sudo", sudo, "--sudoflags=-A", "--sudoloop=false",
                   "--noconfirm", "--editmenu=false", "--combinedupgrade=false", "--useask=false",
                   "--color=never", "--noprogressbar"]
        self.operation_active = True
        self.awaiting_refresh = False
        self.prompt_tail = ""
        self.response_secret = False
        self.response_entry.set_visibility(True)
        self.pages.set_visible_child_name("operation")
        self.page_title.set_label("Atualização em andamento")
        self.page_subtitle.set_label("Acompanhe o processo aqui. A Central solicitará sua senha quando necessário.")
        self.summary.set_title("Preparando a atualização…")
        self.summary.set_subtitle("Mantenha o computador ligado até terminar")
        self.set_notice()
        self.operation_label.set_label("Preparando a atualização…")
        self.operation_log.get_buffer().set_text("")
        self.response_revealer.set_reveal_child(False)
        self.respond_button.set_sensitive(True)
        self.operation_spinner.start()
        self.set_busy(True)
        try:
            self.session = UpdateSession(
                command,
                on_output=lambda text: GLib.idle_add(self._append_operation_output, text),
                on_authentication=lambda request: GLib.idle_add(self._show_password_dialog, request),
                on_exit=lambda code: GLib.idle_add(self._operation_finished, code),
            )
            self.session.start()
        except Exception as exc:
            self.operation_active = False
            self.operation_spinner.stop()
            self.pages.set_visible_child_name("packages")
            self.page_title.set_label("Revise antes de instalar")
            self.page_subtitle.set_label("Confira os nomes e as versões que serão atualizadas.")
            self.summary.set_title("Não foi possível iniciar")
            self.summary.set_subtitle("Confira a mensagem e tente novamente")
            self.set_busy(False)
            self.set_notice(str(exc), True)

    def _append_operation_output(self, text):
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
        text = text.replace("\r", "\n")
        if not text:
            return GLib.SOURCE_REMOVE
        buffer = self.operation_log.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        if buffer.get_char_count() > 250000:
            buffer.delete(buffer.get_start_iter(), buffer.get_iter_at_offset(buffer.get_char_count() - 200000))
        self.operation_log.scroll_to_iter(buffer.get_end_iter(), 0.0, False, 0.0, 1.0)
        self.prompt_tail = (self.prompt_tail + text)[-2000:]
        if self.operation_active and re.search(r"(?:\[[^\]\n]{1,30}/[^\]\n]{1,30}\]|==>|[?:])\s*$", self.prompt_tail):
            self.operation_label.set_label("O yay pode estar aguardando uma resposta")
            prompt = self.prompt_tail.lower()
            last_line = prompt.rstrip().split("\n")[-1]
            self.response_secret = bool(re.search(r"password|passphrase|senha", last_line))
            self.response_entry.set_visibility(not self.response_secret)
            if self.response_secret:
                self.response_hint.set_label("O programa pediu uma informação confidencial; o texto ficará oculto. A senha de administrador é pedida no diálogo da Central.")
            elif "diffs to show" in prompt:
                self.response_hint.set_label("O yay pergunta se deseja revisar alterações do AUR. Digite A para ver todas ou use Continuar para a opção padrão.")
            elif "packages to cleanbuild" in prompt:
                self.response_hint.set_label("O yay pergunta quais pacotes devem ser recompilados do zero. Use Continuar para a opção padrão ou digite a opção desejada.")
            elif re.search(r"\[[^\]\n]{1,30}/[^\]\n]{1,30}\]\s*$", self.prompt_tail):
                self.response_hint.set_label("O yay pede uma confirmação. Escolha Sim, Não ou Continuar para a opção padrão.")
            else:
                self.response_hint.set_label("Responda à pergunta acima. A senha será pedida em um diálogo da Central.")
            self.response_revealer.set_reveal_child(True)
        elif self.operation_active:
            self.operation_label.set_label("Atualização em andamento…")
        return GLib.SOURCE_REMOVE

    def _show_response_controls(self, *_):
        if self.operation_active:
            self.response_revealer.set_reveal_child(True)
            self.response_entry.grab_focus()

    def _send_response(self, answer):
        if self.operation_active and self.session and self.session.send_response(answer, secret=self.response_secret):
            self.response_entry.set_text("")
            self.response_entry.set_visibility(True)
            self.response_secret = False
            self.response_revealer.set_reveal_child(False)
            self.prompt_tail = ""
            self.operation_label.set_label("Resposta enviada. Aguarde…")

    def _show_password_dialog(self, request):
        if not self.operation_active:
            request.respond(None)
            return GLib.SOURCE_REMOVE
        dialog = Adw.MessageDialog(transient_for=self.window, heading="Autenticação necessária",
                                   body="Digite sua senha de administrador para continuar a atualização.")
        dialog.set_modal(True)
        password = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Senha")
        dialog.set_extra_child(password)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("authenticate", "Continuar")
        dialog.set_response_appearance("authenticate", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("authenticate")
        dialog.set_close_response("cancel")
        self.password_dialog = dialog
        self.password_request = request

        def respond(_dialog, response):
            value = password.get_text() if response == "authenticate" else None
            password.set_text("")
            self.password_dialog = None
            self.password_request = None
            request.respond(value)
            dialog.close()

        dialog.connect("response", respond)
        password.connect("activate", lambda *_: dialog.response("authenticate"))
        dialog.present()
        password.grab_focus()
        return GLib.SOURCE_REMOVE

    def _operation_finished(self, code):
        if self.password_dialog:
            self.password_dialog.response("cancel")
        self.operation_active = False
        self.session = None
        self.operation_spinner.stop()
        self.respond_button.set_sensitive(False)
        self.response_revealer.set_reveal_child(False)
        self.awaiting_refresh = True
        self.set_busy(False)
        self.apply_button.set_sensitive(True)
        if code == 0:
            self._request_indicator_refresh()
        self.page_title.set_label("Processo finalizado" if code == 0 else "Atualização interrompida")
        self.page_subtitle.set_label("Confira os detalhes abaixo e volte à lista quando quiser.")
        if code == 0:
            self.summary.set_title("O yay terminou")
            self.summary.set_subtitle("Confira a lista para ver se há atualizações pendentes")
            self.operation_label.set_label("Processo finalizado")
            self.set_notice("Se o kernel ou componentes centrais foram atualizados, reinicie o computador.")
        else:
            self.summary.set_title("A atualização não foi concluída")
            self.summary.set_subtitle(f"O yay terminou com código {code}. Consulte os detalhes abaixo.")
            self.operation_label.set_label("Confira os detalhes da operação")
            self.set_notice("Alguns pacotes podem já ter sido atualizados. Confira os detalhes antes de tentar novamente.", True)
        self.update_primary_button()
        return GLib.SOURCE_REMOVE

    def _request_indicator_refresh(self):
        cache_dir = os.path.join(GLib.get_user_cache_dir(), "arch-update-center")
        temporary_path = None
        try:
            os.makedirs(cache_dir, mode=0o700, exist_ok=True)
            fd, temporary_path = tempfile.mkstemp(prefix=".refresh-", dir=cache_dir)
            with os.fdopen(fd, "w", encoding="utf-8") as marker:
                marker.write("Atualização concluída\n")
            os.replace(temporary_path, os.path.join(cache_dir, "refresh-request"))
        except OSError as exc:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            print(f"Não foi possível solicitar atualização do indicador: {exc}", file=sys.stderr)

    def _on_close_request(self, *_):
        if not self.operation_active:
            return False
        dialog = Adw.MessageDialog(transient_for=self.window, heading="Atualização em andamento",
                                   body="Aguarde a atualização terminar antes de fechar a Central.")
        dialog.add_response("ok", "Entendi")
        dialog.set_close_response("ok")
        dialog.present()
        return True


if __name__ == "__main__":
    UpdateCenter().run()
