import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

const CHECK_INTERVAL_SECONDS = 15 * 60;
const INITIAL_DELAY_SECONDS = 12;
const UPDATE_LINE = /^(\S+)\s+(\S+)\s+->\s+(\S+)(?:\s+\[[^\]]+\])?$/;

export default class ArchUpdateCenterIndicator extends Extension {
    enable() {
        this._disabled = false;
        this._checking = false;
        this._previousSignature = null;
        this._count = 0;

        this._button = new PanelMenu.Button(0.0, 'Atualizações do Arch', true);
        const click = new Clutter.ClickGesture();
        click.connect('recognize', () => this._openUpdateCenter());
        this._button.add_action(click);
        const keyboard = new Clutter.KeyController();
        keyboard.connect('key-press', controller => {
            const [, key] = controller.get_key();
            if (key === Clutter.KEY_Return || key === Clutter.KEY_KP_Enter || key === Clutter.KEY_space) {
                this._openUpdateCenter();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this._button.add_action(keyboard);
        this._button.set_accessible_name('Atualizações do Arch: verificando');

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({
            icon_name: 'software-update-available-symbolic',
            style_class: 'system-status-icon',
        });
        this._countLabel = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._countLabel);
        this._button.add_child(box);
        Main.panel.addToStatusArea(this.uuid, this._button, 1, 'right');

        const refreshDirectory = GLib.build_filenamev([
            GLib.get_user_cache_dir(),
            'arch-update-center',
        ]);
        try {
            this._refreshMonitor = Gio.File.new_for_path(refreshDirectory)
                .monitor_directory(Gio.FileMonitorFlags.NONE, null);
            this._refreshMonitor.connect('changed', (_monitor, file, otherFile, eventType) => {
                const isRefreshRequest = file?.get_basename() === 'refresh-request' ||
                    otherFile?.get_basename() === 'refresh-request';
                const isArrival = eventType === Gio.FileMonitorEvent.CREATED ||
                    eventType === Gio.FileMonitorEvent.MOVED_IN ||
                    eventType === Gio.FileMonitorEvent.RENAMED ||
                    eventType === Gio.FileMonitorEvent.CHANGES_DONE_HINT;
                if (!this._disabled && isRefreshRequest && isArrival)
                    this._checkUpdates();
            });
        } catch (error) {
            console.error(`[${this.uuid}] Não foi possível observar atualizações da Central: ${error.message}`);
        }

        this._initialTimer = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            INITIAL_DELAY_SECONDS,
            () => {
                this._initialTimer = 0;
                this._checkUpdates();
                return GLib.SOURCE_REMOVE;
            }
        );
        this._periodicTimer = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            CHECK_INTERVAL_SECONDS,
            () => {
                this._checkUpdates();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    disable() {
        this._disabled = true;
        if (this._initialTimer) {
            GLib.Source.remove(this._initialTimer);
            this._initialTimer = 0;
        }
        if (this._periodicTimer) {
            GLib.Source.remove(this._periodicTimer);
            this._periodicTimer = 0;
        }
        this._refreshMonitor?.cancel();
        this._refreshMonitor = null;
        this._button?.destroy();
        this._button = null;
    }

    _checkUpdates() {
        if (this._disabled || this._checking)
            return;

        const yay = GLib.find_program_in_path('yay');
        if (!yay) {
            this._countLabel.set_text('!');
            this._button?.set_accessible_name('yay não está instalado. Clique para abrir a Central.');
            return;
        }

        this._checking = true;
        if (this._previousSignature === null) {
            this._countLabel.set_text('…');
            this._button.set_accessible_name('Consultando atualizações com yay');
        }
        try {
            const proc = Gio.Subprocess.new(
                [yay, '-Qu'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            proc.communicate_utf8_async(null, null, (source, result) => {
                this._checking = false;
                if (this._disabled)
                    return;

                try {
                    const [, stdout, stderr] = source.communicate_utf8_finish(result);
                    this._handleResults(stdout ?? '', stderr ?? '');
                } catch (error) {
                    this._countLabel.set_text('!');
                    this._button?.set_accessible_name('Não foi possível consultar as atualizações.');
                    console.error(`[${this.uuid}] Falha em yay -Qu: ${error.message}`);
                }
            });
        } catch (error) {
            this._checking = false;
            this._countLabel.set_text('!');
            this._button?.set_accessible_name('Não foi possível iniciar yay.');
            console.error(`[${this.uuid}] Não foi possível iniciar yay: ${error.message}`);
        }
    }

    _handleResults(stdout, stderr) {
        const lines = stdout.split(/\r?\n/).filter(Boolean);
        const updates = [];
        for (const line of lines) {
            const match = UPDATE_LINE.exec(line.trim());
            if (match)
                updates.push({name: match[1], oldVersion: match[2], newVersion: match[3]});
        }

        if (stderr.trim() || (lines.length > 0 && updates.length === 0)) {
            this._countLabel.set_text('!');
            this._button?.set_accessible_name('Falha ao consultar yay. Clique para abrir a Central.');
            return;
        }

        const signature = updates
            .map(update => `${update.name}:${update.newVersion}`)
            .sort()
            .join('|');
        this._count = updates.length;
        this._countLabel.set_text(this._count > 0 ? String(this._count) : '');

        if (this._count > 0) {
            const updateWord = this._count === 1 ? 'atualização' : 'atualizações';
            const availableWord = this._count === 1 ? 'disponível' : 'disponíveis';
            this._button.set_accessible_name(
                `${this._count} ${updateWord} ${availableWord}; clique para abrir a Central`
            );
            if (this._previousSignature !== null && signature !== this._previousSignature) {
                Main.notify(
                    'Atualizações disponíveis',
                    `yay encontrou ${this._count} pacote${this._count === 1 ? '' : 's'} para atualizar.`
                );
            } else if (this._previousSignature === null) {
                Main.notify(
                    'Atualizações disponíveis',
                    `yay encontrou ${this._count} pacote${this._count === 1 ? '' : 's'} para atualizar.`
                );
            }
        } else {
            this._button.set_accessible_name('Nenhuma atualização encontrada; clique para abrir a Central');
        }

        this._previousSignature = signature;
    }

    _openUpdateCenter() {
        const desktopPath = GLib.build_filenamev([
            GLib.get_user_data_dir(),
            'applications',
            'arch-update-center.desktop',
        ]);

        try {
            const app = GioUnix.DesktopAppInfo.new_from_filename(desktopPath);
            if (app) {
                app.launch([], null);
                return;
            }
        } catch (error) {
            console.error(`[${this.uuid}] Falha ao abrir o atalho: ${error.message}`);
        }

        const executable = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'arch-update-center']);
        try {
            Gio.Subprocess.new([executable], Gio.SubprocessFlags.NONE);
        } catch (error) {
            Main.notify('Central de atualizações', 'Não consegui abrir o app. Reinstale-o com ./install.sh.');
            console.error(`[${this.uuid}] Falha ao abrir a Central: ${error.message}`);
        }
    }
}
