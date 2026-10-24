#!/usr/bin/python3
"""A small GTK 4 front end for complete Arch Linux system upgrades."""

import re
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

        self.activity = Adw.ExpanderRow(title="Detalhes", subtitle="Informações da operação")
        self.log = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                monospace=True, top_margin=10, bottom_margin=10, left_margin=12, right_margin=12)
        log_scroller = Gtk.ScrolledWindow(min_content_height=100, max_content_height=220,
                                          hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        log_scroller.set_child(self.log)
        self.activity.add_row(log_scroller)
        content.append(self.activity)

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
        if len(self.packages) == 1:
            label = "Instalar 1 atualização"
        else:
            label = f"Instalar {len(self.packages)} atualizações" if self.packages else "Nada na lista"
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
        return not query or query in row.package_name.casefold()

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
        self.apply_button.set_label("Instalar atualizações")
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
        pacman = shutil.which("pacman")
        if not pacman:
            GLib.idle_add(self._show_updates, [], "Não encontrei o pacman neste computador.", 1)
            return
        try:
            p = subprocess.run([pacman, "-Qu"], capture_output=True, text=True, timeout=180)
            lines = (p.stdout or "").splitlines()
            entries = []
            for line in lines:
                m = re.match(r"^([^ ]+)\s+([^ ]+)\s+->\s+(.+)$", line.strip())
                if m:
                    entries.append(m.groups())
            err = p.stderr.strip()
            GLib.idle_add(self._show_updates, entries, err, p.returncode)
        except Exception as exc:
            GLib.idle_add(self._show_updates, [], str(exc), 1)

    def _show_updates(self, entries, err, code):
        self.set_busy(False)
        self.apply_button.set_label("Instalar atualizações")
        self.packages = entries
        self.clear_packages()
        for name, old, new in entries:
            row = Adw.ActionRow(title=name, subtitle=f"Versão atual  {old}    →    Nova versão  {new}")
            row.set_title_lines(1)
            row.set_subtitle_lines(2)
            row.set_subtitle_selectable(True)
            row.set_activatable(False)
            row.package_name = name
            self.package_list.append(row)
            self.package_rows.append(row)
        self.count.set_label((f"{len(entries)} pacote" if len(entries) == 1 else f"{len(entries)} pacotes") if entries else "")
        self.search.set_visible(bool(entries))
        if entries:
            self.summary.set_title(f"{len(entries)} atualizações disponíveis")
            self.summary.set_subtitle(f"Lista salva · consultada às {datetime.now().strftime('%H:%M')}")
            self.set_notice("Esta lista não inclui pacotes do AUR. O pacman sincroniza novamente antes da instalação.")
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
            body=f"A consulta encontrou {len(self.packages)} atualizações. Antes de instalar, o pacman vai conferir a lista novamente e atualizar tudo o que estiver disponível. O sistema pedirá sua senha de administrador em uma janela segura. Mantenha o computador ligado até terminar.",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("update", "Instalar atualizações")
        dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("update")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._begin_update)
        dialog.present()

    def on_primary_action(self, *_):
        self.confirm_update()

    def _begin_update(self, dialog, response):
        dialog.close()
        if response != "update":
            return
        pkexec = shutil.which("pkexec")
        pacman = shutil.which("pacman")
        if not pkexec or not pacman:
            self.set_notice("Não encontrei pkexec ou pacman neste sistema.", True)
            return
        self.set_busy(True)
        self.apply_button.set_sensitive(False)
        self.activity.set_expanded(True)
        self.log.get_buffer().set_text("Solicitando autorização do sistema…\n")
        self.summary.set_title("Instalando atualizações…")
        self.summary.set_subtitle("Mantenha o computador ligado. Isso pode levar alguns minutos.")
        threading.Thread(target=self._update_worker, args=(pkexec, pacman), daemon=True).start()

    def _update_worker(self, pkexec, pacman):
        try:
            p = subprocess.Popen([pkexec, pacman, "-Syu", "--noconfirm"], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in p.stdout:
                GLib.idle_add(self._append_log, line)
            code = p.wait()
            GLib.idle_add(self._update_done, code)
        except Exception as exc:
            GLib.idle_add(self._append_log, f"\nErro: {exc}\n")
            GLib.idle_add(self._update_done, 1)

    def _append_log(self, line):
        buf = self.log.get_buffer()
        end = buf.get_end_iter()
        buf.insert(end, line)
        return GLib.SOURCE_REMOVE

    def _update_done(self, code):
        self.set_busy(False)
        if code == 0:
            self.summary.set_title("Atualização concluída")
            self.summary.set_subtitle("O sistema foi atualizado com sucesso")
            self.set_notice("Atualização concluída. Reinicie se o kernel ou componentes centrais foram atualizados.")
            self.packages = []
            self.clear_packages()
            self.count.set_label("")
            self.search.set_visible(False)
            self.update_primary_button()
            self.apply_button.set_sensitive(False)
        else:
            if code == 126:
                self.summary.set_title("Atualização cancelada")
                self.summary.set_subtitle("A autenticação foi cancelada ou não autorizada")
                self.set_notice("Nenhum pacote foi atualizado. Você pode tentar novamente quando quiser.", True)
            else:
                self.summary.set_title("A atualização não terminou")
                self.summary.set_subtitle("Consulte os detalhes para ver o motivo")
                self.set_notice("Confira a saída do pacman antes de tentar novamente.", True)
            self.apply_button.set_sensitive(False)
        return GLib.SOURCE_REMOVE


if __name__ == "__main__":
    UpdateCenter().run()
