"""Ponto de entrada da ferramenta de circulares.

O cálculo factual permanece no subsistema ``uspapo.transporte``. Manter esta
fachada mínima preserva o nome público da ferramenta e evita misturar registro
de tool-call com regras de GTFS, Olho Vivo e planejamento.
"""

import sys

from uspapo.transporte import consultas_circulares as _motor

# Mantém compatibilidade com os imports históricos (`uspapo.ferramentas
# .circulares`) sem duplicar um segundo módulo mutável. Isso também garante que
# instrumentação e mocks apontem para o único motor factual.
sys.modules[__name__] = _motor
