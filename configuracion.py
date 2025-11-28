def _config_cabecera():
    from thonny.editors import Editor

    _original_init = Editor.__init__

    def _hook(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)

        if self.get_filename() is None:
            global ALUMNO_DNI
            cabecera = f"# DNI = {ALUMNO_DNI}\n# EJERCICIO = \n\n"

            try:
                widget = self.get_text_widget()
                widget.insert("1.0", cabecera)
            except Exception:
                self.set_text(cabecera)

    Editor.__init__ = _hook

    def inicial():
        wb = get_workbench()
        ed = wb.get_editor_notebook().get_current_editor()

        global ALUMNO_DNI
        cabecera = f"# DNI = {ALUMNO_DNI}\n# EJERCICIO = \n\n"

        if ed and ed.get_filename() is None:
            try:
                w = ed.get_text_widget()
                w.delete("1.0", "end")
                w.insert("1.0", cabecera)
            except Exception:
                ed.set_text(cabecera)

    wb = get_workbench()
    wb.after(500, inicial)

def _config_vistas():
    wb = get_workbench()

    def activar():
        try:
            wb.show_view("VariablesView", True)
            wb.show_view("ShellView", True)
        except Exception:
            pass

    wb.after(1000, activar)

def _config_guardar_antes():
    wb = get_workbench()

    def necesita_guardar():
        ed = wb.get_editor_notebook().get_current_editor()
        if ed is None:
            return False

        filename = ed.get_filename()

        if filename is None:
            messagebox.showinfo(
                "Guardar archivo",
                "Debes guardar el archivo antes de continuar."
            )
            wb.get_menu("file").invoke_command("save_as")
            return True

        if ed.is_modified():
            messagebox.showinfo(
                "Guardar archivo",
                "Guarda el archivo antes de continuar."
            )
            wb.get_menu("file").invoke_command("save")
            return True

        return False

    def intercept(event=None):
        if necesita_guardar():
            return "break"

    wb.bind("<<RunScript>>", intercept, True)
    wb.bind("<<RunCurrentScript>>", intercept, True)
    wb.bind("<<DebugRun>>", intercept, True)
    wb.bind("<<DebugCurrentScript>>", intercept, True)

# ======================================================================
#                        PUNTO DE ENTRADA
# ======================================================================

def configurar(DATOS_LOADED):
    wb = get_workbench()

    _config_cabecera()
    _config_vistas()
    _config_guardar_antes()

    def crear_menus():
        menu = wb.get_menu("tools")
        if not menu:
            wb.after(500, crear_menus)
            return

        menu.add_separator()
        menu.add_command(
            label="📥 Descargar ficheros",
            command=descargar_ficheros,
        )
        menu.add_command(
            label="✅ Corregir programa",
            command=lambda: corregir_programa(DATOS_LOADED),
        )

    wb.after(1200, crear_menus)
