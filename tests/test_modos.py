"""Pruebas de modos.py.  Ejecutar: python3 tests/test_modos.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import modos as M  # noqa: E402

ok = fails = 0


def check(n, c):
    global ok, fails
    print(("PASS " if c else "FAIL ") + n)
    ok += bool(c)
    fails += (not c)


M.RUTA = os.path.join(tempfile.mkdtemp(), "m.json")
check("sin archivo no recuerda nada", M.buscar("ETH", "buy", 3000.0) is None)
M.guardar("ETH", "buy", 3000.0, "vigilar")
check("recuerda el modo de la misma posición", M.buscar("ETH", "buy", 3000.0) == "vigilar")
check("tolera diferencias mínimas de precio", M.buscar("ETH", "buy", 3000.5) == "vigilar")
check("si la entrada cambia (añadiste a la posición) no la reconoce", M.buscar("ETH", "buy", 2900.0) is None)
check("si cambia el lado no la reconoce", M.buscar("ETH", "sell", 3000.0) is None)
M.guardar("ZEC", "sell", 50.0, "ignorar")
check("recuerda 'ignorar'", M.buscar("ZEC", "sell", 50.0) == "ignorar")
M.guardar("ETH", "buy", 3000.0, "trailing")
check("cambiar de modo se actualiza", M.buscar("ETH", "buy", 3000.0) == "trailing")
M.guardar("SOL", "buy", 100.0, "loco")
check("modos no válidos se ignoran", M.buscar("SOL", "buy", 100.0) is None)
M.olvidar_cerradas({"ETH"})
check("olvida las posiciones ya cerradas", M.buscar("ZEC", "sell", 50.0) is None and M.buscar("ETH", "buy", 3000.0) == "trailing")
open(M.RUTA, "w").write("{roto")
check("archivo dañado: no rompe", M.buscar("ETH", "buy", 3000.0) is None)
M.RUTA = "/proc/no_se_puede/m.json"
M.guardar("ETH", "buy", 3000.0, "trailing")
check("sin permisos de escritura: no rompe", True)

print(f"\n{ok} OK, {fails} fallos")
sys.exit(1 if fails else 0)
