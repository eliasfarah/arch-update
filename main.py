#!/usr/bin/python3
"""A small GTK 4 front end for complete Arch Linux system upgrades."""

import json
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
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from update_backend import UpdateSession


APP_ID = "io.github.farah.archupdatecenter"
APP_VERSION = "0.4.6"
APP_STYLES = b"""
label.category-dot { font-size: 11px; }
label.category-core, .package-accent.category-core { color: #62a0ea; background-color: #62a0ea; }
label.category-extra, .package-accent.category-extra { color: #c061cb; background-color: #c061cb; }
label.category-multilib, .package-accent.category-multilib { color: #33b7a5; background-color: #33b7a5; }
label.category-aur, .package-accent.category-aur { color: #e5a50a; background-color: #e5a50a; }
label.category-other, .package-accent.category-other { color: #8a8a8a; background-color: #8a8a8a; }
label.category-count, label.source-chip {
  border-radius: 999px;
  padding: 3px 9px;
  font-weight: 600;
}
label.category-count.category-core, label.source-chip.category-core { background-color: alpha(#62a0ea, 0.14); }
label.category-count.category-extra, label.source-chip.category-extra { background-color: alpha(#c061cb, 0.14); }
label.category-count.category-multilib, label.source-chip.category-multilib { background-color: alpha(#33b7a5, 0.14); }
label.category-count.category-aur, label.source-chip.category-aur { background-color: alpha(#e5a50a, 0.16); }
label.category-count.category-other, label.source-chip.category-other { background-color: alpha(#8a8a8a, 0.14); }
.package-accent { border-radius: 3px; }
label.package-status-done { color: #2ec27e; font-weight: 600; }
image.package-status-done { color: #2ec27e; }
.package-activity { color: @accent_color; min-width: 24px; min-height: 24px; }
label.package-status-failed { color: #e01b24; font-weight: 600; }
label.package-status-pending { color: alpha(currentColor, 0.62); }
label.package-status-skipped { color: alpha(currentColor, 0.62); }
"""

PACMAN_ACTION = re.compile(
    r"\(\s*(\d+)\s*/\s*(\d+)\)\s+"
    r"(upgrading|installing|reinstalling|downgrading|removing)\s+"
    r"([^\s]+?)(?:\.{3,})?\s*$",
    re.IGNORECASE,
)
PACMAN_ACTION_LABELS = {
    "upgrading": "Atualizando",
    "installing": "Instalando",
    "reinstalling": "Reinstalando",
    "downgrading": "Revertendo",
    "removing": "Removendo",
}


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
        self.operation_package_rows = {}
        self.operation_finished_view = False
        self.operation_parse_buffer = ""
        self.operation_current_package = None
        self.operation_current_action = "installing"

    def on_activate(self, _app):
        if hasattr(self, "window"):
            self.window.present()
            if not self.busy:
                self.refresh()
            return
        self.window = Adw.ApplicationWindow(application=self, title="Atualizações do sistema")
        self._install_styles()
        self.window.set_default_size(840, 720)
        self.window.set_size_request(580, 520)
        self.window.connect("close-request", self._on_close_request)
        self.build_ui()
        self.window.present()
        self.refresh()

    def _install_styles(self):
        display = Gdk.Display.get_default()
        if display is None:
            return
        self.style_provider = Gtk.CssProvider()
        self.style_provider.load_from_data(APP_STYLES)
        Gtk.StyleContext.add_provider_for_display(
            display,
            self.style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.set_content(root)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Atualizações", css_classes=["title"]))
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about)
        self.add_action(about_action)
        menu = Gio.Menu()
        menu.append("Sobre a Central de atualizações", "app.about")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu principal")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
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

        self.loading_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                                    halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.loading_spinner = Gtk.Spinner()
        self.loading_spinner.set_size_request(48, 48)
        self.loading_spinner.add_css_class("package-activity")
        self.loading_page.append(self.loading_spinner)
        loading_title = Gtk.Label(label="Buscando atualizações", css_classes=["heading"])
        self.loading_page.append(loading_title)
        loading_detail = Gtk.Label(label="Consultando os repositórios e o AUR…", css_classes=["dim-label"])
        self.loading_page.append(loading_detail)
        self.pages.add_named(self.loading_page, "loading")
        self.empty_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                                  halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        empty_label = Gtk.Label(label="Nenhum pacote disponível", css_classes=["heading", "dim-label"])
        self.empty_page.append(empty_label)
        check_again = Gtk.Button(label="Verificar novamente", halign=Gtk.Align.CENTER)
        check_again.add_css_class("pill")
        check_again.connect("clicked", lambda *_: self.refresh())
        self.empty_page.append(check_again)
        self.pages.add_named(self.empty_page, "empty")

        self.operation_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, vexpand=True)
        self.pages.add_named(self.operation_page, "operation")
        operation_header = Gtk.Box(spacing=10)
        self.operation_spinner = Gtk.Spinner()
        operation_header.append(self.operation_spinner)
        self.operation_label = Gtk.Label(label="Preparando a atualização…", xalign=0, hexpand=True)
        self.operation_label.add_css_class("heading")
        operation_header.append(self.operation_label)
        self.operation_page.append(operation_header)

        self.operation_progress_label = Gtk.Label(label="Preparando a lista de pacotes…", xalign=0)
        self.operation_progress_label.add_css_class("dim-label")
        self.operation_page.append(self.operation_progress_label)
        self.operation_progress = Gtk.ProgressBar(show_text=False)
        self.operation_page.append(self.operation_progress)

        self.operation_package_placeholder = Gtk.Label(
            label="A lista aparecerá quando o yay iniciar a instalação.",
            margin_top=18, margin_bottom=18,
        )
        self.operation_package_placeholder.add_css_class("dim-label")
        self.operation_package_list = Gtk.ListBox()
        self.operation_package_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.operation_package_list.set_placeholder(self.operation_package_placeholder)
        self.operation_package_list.set_filter_func(self._filter_operation_package)
        self.operation_package_scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=150,
                                                              hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.operation_package_scroller.add_css_class("boxed-list")
        self.operation_package_scroller.set_child(self.operation_package_list)
        self.operation_page.append(self.operation_package_scroller)

        self.operation_log_toggle = Gtk.ToggleButton(label="Ver terminal", icon_name="utilities-terminal-symbolic")
        self.operation_log_toggle.add_css_class("flat")
        self.operation_log_toggle.set_halign(Gtk.Align.START)
        self.operation_page.append(self.operation_log_toggle)

        self.operation_log = Gtk.TextView(editable=False, cursor_visible=False,
                                         wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True,
                                         top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        log_scroller = Gtk.ScrolledWindow(vexpand=False, min_content_height=115, max_content_height=190,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER)
        log_scroller.add_css_class("card")
        log_scroller.set_child(self.operation_log)
        self.operation_log_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.operation_log_revealer.set_reveal_child(False)
        self.operation_log_revealer.set_child(log_scroller)
        self.operation_page.append(self.operation_log_revealer)
        self.operation_log_toggle.connect("toggled", self._toggle_operation_log)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.bottom_box = bottom
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
        self.bottom_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        root.append(self.bottom_separator)
        root.append(bottom)

    def _show_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name="Central de atualizações do Arch",
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name="Elias Farah",
            website="https://github.com/eliasfarah/arch-update",
            issue_url="https://github.com/eliasfarah/arch-update/issues",
            comments="Consulte e instale atualizações do Arch Linux e do AUR.",
        )
        dialog.present(self.window)

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
        if query:
            visible_count = sum(
                query.casefold() in row.package_name.casefold()
                or query.casefold() in row.package_source
                for row in self.package_rows
            )
            self.count.set_label(f"{visible_count} de {len(self.package_rows)}")
        elif self.packages:
            total = len(self.package_rows)
            self.count.set_label(f"{total} pacote" if total == 1 else f"{total} pacotes")
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
        for widget in (self.page_title, self.page_subtitle, self.bottom_box, self.bottom_separator):
            widget.set_visible(True)
        self.awaiting_refresh = False
        self.query_ok = False
        self.pages.set_visible_child_name("loading")
        self.loading_spinner.start()
        self.page_title.set_label("Revise antes de instalar")
        self.page_subtitle.set_label("Confira os nomes e as versões que serão atualizadas.")
        self.refresh_button.set_sensitive(True)
        self.set_busy(True)
        self.set_notice()
        self.count.set_label("")
        self.search.set_text("")
        self.search.set_visible(False)
        self.clear_packages()
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        checker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update_checker.py")
        if not os.path.isfile(checker):
            GLib.idle_add(self._show_updates, [], "O componente de consulta está ausente. Reinstale o aplicativo.", 1)
            return
        try:
            result = subprocess.run(
                [sys.executable, checker, "--force"],
                capture_output=True,
                text=True,
                timeout=360,
            )
            data = json.loads(result.stdout)
            entries = [
                (item["name"], item["oldVersion"], item["newVersion"], item["group"], item["source"])
                for item in data.get("updates", [])
            ]
            error = data.get("error", "")
            GLib.idle_add(self._show_updates, entries, error, result.returncode)
        except Exception as exc:
            GLib.idle_add(self._show_updates, [], str(exc), 1)

    def _show_updates(self, entries, err, code):
        self.loading_spinner.stop()
        self.pages.set_visible_child_name("packages")
        self.package_placeholder.set_text(
            "Não foi possível carregar os pacotes" if err or code not in (0, 1, 2)
            else "Nenhuma atualização disponível"
        )
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
        group_counts = {}
        for _name, _old, _new, group, _source in entries:
            group_counts[group] = group_counts.get(group, 0) + 1
        for name, old, new, group, source in entries:
            if group != current_group:
                heading = Gtk.ListBoxRow()
                heading.set_selectable(False)
                heading.set_activatable(False)
                heading.is_group_heading = True
                heading.package_group = group
                heading_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
                heading_box.set_margin_top(13)
                heading_box.set_margin_bottom(6)
                heading_box.set_margin_start(16)
                heading_box.set_margin_end(16)
                category_dot = Gtk.Label(label="●")
                category_dot.add_css_class("category-dot")
                category_dot.add_css_class(f"category-{group}")
                heading_label = Gtk.Label(label=group_titles[group], xalign=0, hexpand=True)
                heading_label.add_css_class("heading")
                heading_count = Gtk.Label(label=str(group_counts[group]))
                heading_count.add_css_class("category-count")
                heading_count.add_css_class(f"category-{group}")
                heading_box.append(category_dot)
                heading_box.append(heading_label)
                heading_box.append(heading_count)
                heading.set_child(heading_box)
                self.package_list.append(heading)
                current_group = group
            row = Adw.ActionRow(title=name, subtitle=f"Versão atual  {old}    →    Nova versão  {new}")
            row.set_title_lines(1)
            row.set_subtitle_lines(2)
            row.set_subtitle_selectable(True)
            row.set_activatable(False)
            source_label = Gtk.Label(label=source)
            source_label.add_css_class("dim-label")
            source_label.add_css_class("source-chip")
            source_label.add_css_class(f"category-{group}")
            row.add_suffix(source_label)
            accent = Gtk.Box()
            accent.set_size_request(4, 30)
            accent.set_valign(Gtk.Align.CENTER)
            accent.add_css_class("package-accent")
            accent.add_css_class(f"category-{group}")
            row.add_prefix(accent)
            row.set_selectable(False)
            row.package_name = name
            row.package_source = source.casefold()
            row.package_group = group
            self.package_list.append(row)
            self.package_rows.append(row)
        self.count.set_label((f"{len(entries)} pacote" if len(entries) == 1 else f"{len(entries)} pacotes") if entries else "")
        self.search.set_visible(bool(entries))
        if entries:
            self.page_title.set_label("Atualizações disponíveis")
            self.page_subtitle.set_label(f"Consultado às {datetime.now().strftime('%H:%M')} · A lista pode mudar antes da instalação.")
            self.set_notice()
        elif not err and code in (0, 1, 2):
            self.pages.set_visible_child_name("empty")
            self.set_notice()
            for widget in (self.page_title, self.page_subtitle, self.bottom_box, self.bottom_separator):
                widget.set_visible(False)
        else:
            self.page_title.set_label("Não foi possível procurar atualizações")
            self.page_subtitle.set_label("Confira a mensagem e tente novamente.")
            self.set_notice(err or "Confira a conexão com a internet e tente novamente.", True)
        self.apply_button.set_sensitive(self.query_ok)
        self.update_primary_button()
        return GLib.SOURCE_REMOVE

    def on_primary_action(self, *_):
        if self.awaiting_refresh:
            self.refresh()
        else:
            self._begin_update()

    def _toggle_operation_log(self, button):
        visible = button.get_active()
        self.operation_log_revealer.set_reveal_child(visible)
        button.set_label("Ocultar terminal" if visible else "Ver terminal")

    def _clear_operation_packages(self):
        child = self.operation_package_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.operation_package_list.remove(child)
            child = nxt
        self.operation_package_rows.clear()
        self.operation_finished_view = False
        self.operation_package_list.invalidate_filter()
        self.operation_current_package = None
        self.operation_current_action = "installing"
        self.operation_parse_buffer = ""

    def _add_operation_package(self, name, old="", new="", group="other", source=""):
        if name in self.operation_package_rows:
            return self.operation_package_rows[name]
        row = Adw.ActionRow(title=name)
        row.set_title_lines(1)
        if old or new:
            row.set_subtitle(f"{old}  →  {new}")
        elif source:
            row.set_subtitle(source)
        row.set_activatable(False)
        row.set_selectable(False)
        row.operation_state = "pending"
        if group in {"core", "extra", "multilib", "aur", "other"}:
            accent = Gtk.Box()
            accent.set_size_request(4, 28)
            accent.set_valign(Gtk.Align.CENTER)
            accent.add_css_class("package-accent")
            accent.add_css_class(f"category-{group}")
            row.add_prefix(accent)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_valign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.set_size_request(24, 24)
        spinner.add_css_class("package-activity")
        spinner.set_visible(False)
        status_box.append(spinner)
        status = Gtk.Label(label="Aguardando", css_classes=["caption", "package-status-pending"])
        status_box.append(status)
        check = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        check.add_css_class("package-status-done")
        check.set_visible(False)
        status_box.append(check)
        row.add_suffix(status_box)
        self.operation_package_list.append(row)
        self.operation_package_rows[name] = {
            "row": row, "spinner": spinner, "status": status, "check": check,
        }
        return self.operation_package_rows[name]

    def _filter_operation_package(self, row):
        return not self.operation_finished_view or getattr(row, "operation_state", "pending") in ("done", "failed")

    def _set_operation_package_status(self, name, state, action="installing"):
        widgets = self.operation_package_rows.get(name)
        if not widgets:
            widgets = self._add_operation_package(name)
        spinner = widgets["spinner"]
        status = widgets["status"]
        check = widgets["check"]
        widgets["row"].operation_state = state
        spinner.stop()
        spinner.set_visible(state == "running")
        if state == "running":
            spinner.start()
            status.set_label(PACMAN_ACTION_LABELS.get(action, "Processando"))
            status.set_css_classes(["caption"])
            check.set_visible(False)
        elif state == "done":
            status.set_label("Concluído")
            status.set_css_classes(["caption"])
            check.set_visible(True)
        elif state == "failed":
            status.set_label("Falhou")
            status.set_css_classes(["caption", "package-status-failed"])
            check.set_visible(False)
        elif state == "skipped":
            status.set_label("Não foi necessário")
            status.set_css_classes(["caption", "package-status-skipped"])
            check.set_visible(False)
        else:
            status.set_label("Aguardando")
            status.set_css_classes(["caption", "package-status-pending"])
            check.set_visible(False)
        self._update_operation_progress()

    def _update_operation_progress(self):
        total = len(self.operation_package_rows)
        completed = sum(
            1 for item in self.operation_package_rows.values()
            if item["check"].get_visible()
        )
        running = self.operation_current_package
        if total:
            action_label = PACMAN_ACTION_LABELS.get(self.operation_current_action, "Processando")
            self.operation_progress_label.set_label(
                f"{completed} de {total} concluídos"
                + (f" · {action_label} {running}" if running else "")
            )
            self.operation_progress.set_fraction(min(completed / total, 1.0))
            self.operation_progress.set_text(f"{completed} de {total}")
        else:
            self.operation_progress_label.set_label("Aguardando os pacotes do yay…")
            self.operation_progress.set_fraction(0)
            self.operation_progress.set_text("")

    def _track_operation_output(self, text):
        self.operation_parse_buffer += text.replace("\r", "\n")
        lines = self.operation_parse_buffer.split("\n")
        self.operation_parse_buffer = lines.pop()
        for line in lines:
            match = PACMAN_ACTION.search(line)
            if not match:
                continue
            _index, _total, action, name = match.groups()
            if self.operation_current_package and self.operation_current_package != name:
                self._set_operation_package_status(self.operation_current_package, "done")
            self.operation_current_package = name
            self.operation_current_action = action.casefold()
            self._set_operation_package_status(name, "running", self.operation_current_action)

    def _begin_update(self):
        if self.busy or not self.query_ok:
            return
        yay = shutil.which("yay")
        sudo = shutil.which("sudo")
        if not yay or not sudo:
            self.set_notice("Preciso encontrar yay e sudo para continuar.", True)
            return

        command = [yay, "-Syyu", "--sudo", sudo, "--sudoflags=-A", "--sudoloop=false",
                   "--noconfirm", "--answerupgrade", "None", "--answerclean", "None",
                   "--answerdiff", "None", "--answeredit", "None", "--cleanmenu=false",
                   "--diffmenu=false", "--editmenu=false", "--noremovemake",
                   "--combinedupgrade=false", "--useask=false", "--color=never", "--noprogressbar"]
        self.operation_active = True
        self.awaiting_refresh = False
        self.pages.set_visible_child_name("operation")
        self.page_title.set_label("Atualização em andamento")
        self.page_subtitle.set_label("Acompanhe o processo aqui. A Central solicitará sua senha quando necessário.")
        self.page_subtitle.set_label("Mantenha o computador ligado até terminar.")
        self.set_notice()
        self.operation_label.set_label("Preparando a atualização…")
        self.operation_log.get_buffer().set_text("")
        self.operation_log_toggle.set_active(False)
        self.operation_log_revealer.set_reveal_child(False)
        self.operation_log_toggle.set_label("Ver terminal")
        self._clear_operation_packages()
        for name, old, new, group, source in self.packages:
            self._add_operation_package(name, old, new, group, source)
        self._update_operation_progress()
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
            self.page_title.set_label("Não foi possível iniciar")
            self.set_busy(False)
            self.set_notice(str(exc), True)

    def _append_operation_output(self, text):
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
        self._track_operation_output(text)
        text = text.replace("\r", "\n")
        if not text:
            return GLib.SOURCE_REMOVE
        buffer = self.operation_log.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        if buffer.get_char_count() > 250000:
            buffer.delete(buffer.get_start_iter(), buffer.get_iter_at_offset(buffer.get_char_count() - 200000))
        self.operation_log.scroll_to_iter(buffer.get_end_iter(), 0.0, False, 0.0, 1.0)
        if self.operation_active:
            self.operation_label.set_label("Atualização em andamento…")
        return GLib.SOURCE_REMOVE

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
        if self.operation_parse_buffer:
            match = PACMAN_ACTION.search(self.operation_parse_buffer)
            if match:
                _index, _total, action, name = match.groups()
                self.operation_current_package = name
                self.operation_current_action = action.casefold()
                self._set_operation_package_status(name, "running", self.operation_current_action)
            self.operation_parse_buffer = ""
        if code == 0:
            if self.operation_current_package:
                self._set_operation_package_status(self.operation_current_package, "done")
            self.operation_current_package = None
            self._update_operation_progress()
            for name, widgets in self.operation_package_rows.items():
                if not widgets["check"].get_visible():
                    self._set_operation_package_status(name, "skipped")
        elif self.operation_current_package:
            self._set_operation_package_status(self.operation_current_package, "failed")
            self.operation_current_package = None
            self._update_operation_progress()
        if self.password_dialog:
            self.password_dialog.response("cancel")
        self.operation_active = False
        self.operation_finished_view = True
        self.operation_package_list.invalidate_filter()
        completed = sum(item["row"].operation_state == "done" for item in self.operation_package_rows.values())
        self.operation_package_placeholder.set_label("Nenhum pacote foi processado nesta operação.")
        self.session = None
        self.operation_spinner.stop()
        self.awaiting_refresh = True
        self.set_busy(False)
        self.apply_button.set_sensitive(True)
        if code == 0:
            self._request_indicator_refresh()
        self.page_title.set_label("Processo finalizado" if code == 0 else "Atualização interrompida")
        self.page_subtitle.set_label("Confira os pacotes processados nesta operação.")
        if code == 0:
            self.operation_label.set_label("Atualização concluída")
            self.operation_progress_label.set_label(f"{completed} pacote" + ("s" if completed != 1 else "") + " processado" + ("s" if completed != 1 else ""))
            self.set_notice("Se o kernel ou componentes centrais foram atualizados, reinicie o computador.")
        else:
            self.operation_label.set_label("Confira os detalhes da operação")
            self.operation_progress_label.set_label(f"{completed} pacote" + ("s" if completed != 1 else "") + " concluído" + ("s" if completed != 1 else ""))
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
