# -*- coding: utf-8 -*-
"""
descargar_ficheros.py — módulo ejecutado bajo demanda
"""

import urllib.request, zipfile, io
from tkinter import filedialog, messagebox

ZIP_URL = "https://github.com/FI-UMH/Thonny-Ficheros/archive/refs/heads/main.zip"


def run():
    carpeta = filedialog.askdirectory(title="Selecciona carpeta destino")
    if not carpeta:
        return

    try:
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "ThonnyFileLoader"})
        data = urllib.request.urlopen(req, timeout=20).read()

        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                out = name.split("/", 1)[1]
                with open(carpeta + "/" + out, "wb") as f:
                    f.write(z.read(name))

        messagebox.showinfo("OK", "Ficheros descargados correctamente.")
    except Exception as e:
        messagebox.showerror("Error", str(e))
