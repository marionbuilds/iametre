"""Typographie partagée entre la couche données et la couche rendu.

Module NEUTRE : il n'importe rien du projet (ARCHITECTURE.md §1). La couche
données l'utilise pour composer les phrases d'interprétation — seule exception
où un nombre formaté vit dans le dictionnaire —, la couche rendu pour tout
l'affichage. Aucun import direct entre données et rendu, dans aucun sens.
"""

from __future__ import annotations


def nb(x, dec: int = 1) -> str:
    """Nombre à la française : virgule décimale. « 10.6 » est une faute en
    français, et ça saute aux yeux sur un produit qui vise ce marché."""
    return f"{x:.{dec}f}".replace(".", ",")


def points(x) -> str:
    """Accord de « point » en PROSE : singulier sous 2 (« 0,8 point »),
    pluriel au-delà (« 6,1 points »). Règle transverse validée le 06/08 :
    les contextes compacts et chiffrés (badge, règle graduée, marges
    « ±6,9 pts ») gardent l'abréviation invariable « pts »."""
    return "point" if abs(x) < 2 else "points"
