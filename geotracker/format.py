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
