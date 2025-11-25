# -*- coding: utf-8 -*-
"""
Plugin: descargar_configuracion
Descarga y ejecuta configuracion.py + carga en memoria el repo Thonny-Datos.
"""

import sys, io, types, urllib.request, zipfile, threading

# --------------------------------------------------------
# URLs de los repositorios
# --------------------------------------------------------

URL_CONFIG = "https://raw.githubusercontent.com/FI-UMH/Thonny-Modulos/main/configuracion.py"
URL_DATOS_ZIP = "https://github.com/FI-UMH/Thonny-Datos/archive/refs/heads/main.zip"


def _download_raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ThonnyConfigLoader"})
    return urllib.request.urlopen(req, timeout=20).read()


def _download_zip(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ThonnyDataLoader"})
    return urllib.request.urlopen(req, timeout=20).read()


def load_plugin():
    threading.Thread(target=_bootstrap, daemon=True).start()


def _bootstrap():
    # --------------------------------------------------------
    # 1. Descargar configuracion.py
    # --------------------------------------------------------
    try:
        raw_conf = _download_raw(URL_CONFIG)
        conf_code = raw_conf.decode("utf-8")
    except Exception as e:
        print("❌ Error descargando configuracion.py:", e)
        return

    # --------------------------------------------------------
    # 2. Descargar REPOSITORIO COMPLETO DE DATOS
    # --------------------------------------------------------
    DATOS_LOADED = {}

    try:
        zip_bytes = _download_zip(URL_DATOS_ZIP)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for name in z.namelist():
                if not name.endswith("/"):
                    short = name.split("/", 1)[1]
                    DATOS_LOADED[short] = z.read(name)
    except Exception as e:
        print("❌ Error descargando Thonny-Datos:", e)
        return

    # --------------------------------------------------------
    # 3. Ejecutar configuracion.py en módulo temporal
    # --------------------------------------------------------
    mod = types.ModuleType("mod_configuracion")

    try:
        exec(conf_code, mod.__dict__)
    except Exception as e:
        print("❌ Error ejecutando configuracion.py:", e)
        return

    # --------------------------------------------------------
    # 4. Llamar a configurar() pasándole los datos
    # --------------------------------------------------------
    if hasattr(mod, "configurar"):
        try:
            mod.configurar(DATOS_LOADED)
        except Exception as e:
            print("❌ Error en configurar():", e)

    # --------------------------------------------------------
    # 5. Eliminar configuracion.py de sys.modules para no persistirlo
    # --------------------------------------------------------
    if "mod_configuracion" in sys.modules:
        del sys.modules["mod_configuracion"]
