"""Mapeamento de nomes de ossos para slots canonicos de humanoide, e o plano de retarget.

Nao depende de bpy. Um "slot" e uma parte do corpo independente da convencao de
nomes do rig (ex.: ``l_arm`` = braco esquerdo, do ombro ao cotovelo).

Fonte fixa: esqueleto SOMA 77 do Kimodo.
"""

from __future__ import annotations

import re

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
SIDES = (("l", "Left"), ("r", "Right"))

# Slot -> nomes aceitos (depois de normalizar: sem lado, sem separadores, minusculo).
ALIASES = {
    "hips": ("hips", "hip", "pelvis"),
    "head": ("head",),
    "shoulder": ("shoulder", "clavicle", "collar", "collarbone"),
    "arm": ("arm", "upperarm", "uparm"),
    "forearm": ("forearm", "lowerarm"),
    "hand": ("hand", "wrist"),
    "upleg": ("upleg", "upperleg", "thigh"),
    "leg": ("leg", "lowerleg", "calf", "shin"),
    "foot": ("foot", "ankle"),
    "toe": ("toebase", "toe", "toes", "toe0", "ball"),
}
_BASE_TO_SLOT = {alias: slot for slot, names in ALIASES.items() for alias in names}
_CENTER_SLOTS = ("hips", "head")
# Esqueleto de captura (XSens, BVH de pesquisa): cada osso leva o nome da junta em que
# comeca. "Shoulder" e o braco, "Elbow" o antebraco, "Hip" com lado a coxa, "Knee" a canela.
_JOINT_TO_SLOT = {"collar": "shoulder", "clavicle": "shoulder", "shoulder": "arm", "elbow": "forearm", "wrist": "hand", "hip": "upleg", "knee": "leg", "ankle": "foot"}

_PREFIX = re.compile(r"^(?:mixamorig\d*[_:]?|j_(?:bip|sec|adj)_|bip\d*[ _]?|def-)", re.I)
_SIDE_RULES = (
    re.compile(r"^(?P<s>left|right)(?=.)", re.I),
    re.compile(r"(?<=.)[ _.\-]?(?P<s>left|right)$", re.I),
    re.compile(r"^(?P<s>[lr])[ _.\-]", re.I),
    re.compile(r"[ _.\-](?P<s>[lr])$", re.I),
)
_CENTER_PREFIX = re.compile(r"^c[ _.\-]", re.I)
_FINGER = re.compile(
    r"^(?:hand)?f?(?P<f>thumb|index|middle|ring|pinky|little)(?:finger)?"
    r"(?:0?(?P<n>[1-4])|(?P<w>proximal|intermediate|distal))$"
)
_PHALANX = {"proximal": 1, "intermediate": 2, "distal": 3}

REQUIRED_SLOTS = ["hips", "head"] + [
    f"{s}_{part}" for s, _ in SIDES for part in ("arm", "forearm", "hand", "upleg", "leg", "foot")
]
OPTIONAL_SLOTS = [f"{s}_{part}" for s, _ in SIDES for part in ("shoulder", "toe")] + [
    f"{s}_{f}{i}" for s, _ in SIDES for f in FINGERS for i in (1, 2, 3)
]

SLOT_LABELS = {
    "hips": "quadril",
    "head": "cabeça",
    "shoulder": "clavícula",
    "arm": "braço",
    "forearm": "antebraço",
    "hand": "mão",
    "upleg": "coxa",
    "leg": "canela",
    "foot": "pé",
    "toe": "dedos do pé",
    "thumb": "polegar",
    "index": "indicador",
    "middle": "médio",
    "ring": "anelar",
    "pinky": "mínimo",
}

SOMA_TORSO = ("Spine1", "Spine2", "Chest")
SOMA_NECK = ("Neck1", "Neck2")


def soma_joint_for_slot(slot: str) -> str:
    """Junta do SOMA 77 que alimenta um slot."""
    if slot == "hips":
        return "Hips"
    if slot == "head":
        return "Head"
    side, part = slot.split("_", 1)
    prefix = "Left" if side == "l" else "Right"
    body = {
        "shoulder": "Shoulder",
        "arm": "Arm",
        "forearm": "ForeArm",
        "hand": "Hand",
        "upleg": "Leg",  # no SOMA, "Leg" e a coxa
        "leg": "Shin",
        "foot": "Foot",
        "toe": "ToeBase",
    }
    if part in body:
        return prefix + body[part]
    finger, n = part[:-1], int(part[-1])
    # O SOMA tem o metacarpo como junta 1 nos quatro dedos longos; o polegar nao.
    soma_n = n if finger == "thumb" else n + 1
    return f"{prefix}Hand{finger.capitalize()}{soma_n}"


def slot_label(slot: str) -> str:
    if "_" not in slot:
        return SLOT_LABELS.get(slot, slot)
    side, part = slot.split("_", 1)
    lado = "esq." if side == "l" else "dir."
    if part[-1].isdigit():
        return f"{SLOT_LABELS.get(part[:-1], part[:-1])} {part[-1]} {lado}"
    return f"{SLOT_LABELS.get(part, part)} {lado}"


def parse_bone_name(name: str) -> tuple[str | None, str]:
    """Devolve (lado, base): lado 'l'/'r'/None e a base normalizada."""
    n = name.split(":")[-1].split("|")[-1]
    n = _PREFIX.sub("", n)
    n = _CENTER_PREFIX.sub("", n)
    side = None
    for rule in _SIDE_RULES:
        m = rule.search(n)
        if m:
            side = m.group("s")[0].lower()
            n = n[: m.start()] + n[m.end() :]
            break
    return side, re.sub(r"[^a-z0-9]", "", n.lower())


def named_by_joint(bone_names: list[str]) -> bool:
    """O esqueleto chama os ossos pela junta (convencao de captura)? Cotovelo e joelho entregam."""
    bases = {parse_bone_name(n) for n in bone_names}
    return all((side, base) in bases for side in ("l", "r") for base in ("elbow", "knee"))


def slot_for_bone(name: str, by_joint: bool = False) -> str | None:
    side, base = parse_bone_name(name)
    if by_joint and side and base in _JOINT_TO_SLOT:
        return f"{side}_{_JOINT_TO_SLOT[base]}"
    if base in _BASE_TO_SLOT:
        slot = _BASE_TO_SLOT[base]
        if slot in _CENTER_SLOTS:
            return slot if side is None else None
        return f"{side}_{slot}" if side else None
    m = _FINGER.match(base)
    if m and side:
        finger = "pinky" if m.group("f") == "little" else m.group("f")
        n = int(m.group("n")) if m.group("n") else _PHALANX[m.group("w")]
        return f"{side}_{finger}{n}" if n <= 3 else None
    return None


def detect_rig_type(bone_names: list[str]) -> dict:
    if not bone_names:
        return {"type": "sem_rig", "label": "Sem rig", "prefix": None}
    for n in bone_names:
        m = re.match(r"^(mixamorig\d*[_:])", n, re.I)
        if m:
            return {"type": "mixamo", "label": "Mixamo", "prefix": m.group(1)}
    if any(n.startswith(("MCH-", "ORG-")) for n in bone_names):
        return {"type": "rigify", "label": "Rigify (rig de controle)", "prefix": None}
    plain = set(bone_names)
    if {"Hips", "LeftUpLeg", "LeftForeArm", "RightHand", "Spine2"} <= plain:
        return {"type": "mixamo", "label": "Mixamo (sem prefixo)", "prefix": ""}
    if {"pelvis", "spine_01", "upperarm_l", "calf_r"} <= plain:
        return {"type": "unreal", "label": "Unreal Mannequin", "prefix": None}
    by_joint = named_by_joint(bone_names)
    slots = {slot_for_bone(n, by_joint) for n in bone_names} - {None}
    if len(slots & set(REQUIRED_SLOTS)) >= 10:
        return {"type": "humanoide", "label": "Humanoide (convenção reconhecida)", "prefix": None}
    return {"type": "desconhecido", "label": "Rig não reconhecido", "prefix": None}


def _path_up(bone: str, parents: dict[str, str | None]) -> list[str]:
    path = [bone]
    while parents.get(path[-1]):
        path.append(parents[path[-1]])
    return path


def _lca(a: str, b: str, parents: dict[str, str | None]) -> str | None:
    up_a = _path_up(a, parents)
    seen = set(up_a)
    for bone in _path_up(b, parents):
        if bone in seen:
            return bone
    return None


def _chain_between(lower: str, upper: str, parents: dict[str, str | None]) -> list[str] | None:
    """Ossos de ``lower`` (exclusivo) ate ``upper`` (inclusivo), de baixo para cima."""
    up = _path_up(upper, parents)
    if lower not in up:
        return None
    return list(reversed(up[: up.index(lower)]))


def build_mapping(bones: list[tuple[str, str | None]], override: dict | None = None) -> dict:
    """Mapeia os ossos do alvo. ``bones`` = [(nome, nome_do_pai), ...]."""
    parents = dict(bones)
    depth = {name: len(_path_up(name, parents)) for name, _ in bones}
    notes: list[str] = []

    by_joint = named_by_joint([name for name, _ in bones])
    slots: dict[str, str] = {}
    for name, _ in sorted(bones, key=lambda b: depth[b[0]]):
        slot = slot_for_bone(name, by_joint)
        if slot is None:
            continue
        if slot in slots:
            notes.append(f"'{name}' também parece ser {slot_label(slot)}; usando '{slots[slot]}'.")
            continue
        slots[slot] = name

    if "hips" not in slots and "l_upleg" in slots and "r_upleg" in slots:
        hips = _lca(parents[slots["l_upleg"]] or "", parents[slots["r_upleg"]] or "", parents)
        if hips:
            slots["hips"] = hips
            notes.append(f"Quadril deduzido pela hierarquia: '{hips}'.")

    override = override or {}
    for slot, bone in (override.get("slots") or {}).items():
        if bone is None:
            slots.pop(slot, None)
        elif bone in parents:
            slots[slot] = bone
        else:
            notes.append(f"Mapeamento manual ignorado: osso '{bone}' não existe ({slot}).")

    torso: list[str] = []
    neck: list[str] = []
    hips = slots.get("hips")
    left = slots.get("l_shoulder") or slots.get("l_arm")
    right = slots.get("r_shoulder") or slots.get("r_arm")
    if hips and left and right:
        chest = _lca(parents[left] or "", parents[right] or "", parents)
        chain = _chain_between(hips, chest, parents) if chest else None
        if chain:
            torso = chain
            head = slots.get("head")
            neck_chain = _chain_between(chest, head, parents) if head else None
            if neck_chain:
                neck = neck_chain[:-1]
        else:
            notes.append("Braços não descem do quadril por uma coluna: tronco não mapeado.")
    if override.get("torso") is not None:
        torso = [b for b in override["torso"] if b in parents]
    if override.get("neck") is not None:
        neck = [b for b in override["neck"] if b in parents]

    missing_required = [s for s in REQUIRED_SLOTS if s not in slots]
    if not torso:
        missing_required.append("torso")
    missing_optional = [s for s in OPTIONAL_SLOTS if s not in slots]
    total = len(REQUIRED_SLOTS) + len(OPTIONAL_SLOTS)
    return {
        "slots": slots,
        "torso": torso,
        "neck": neck,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "coverage": {"mapped": total - len([s for s in missing_required if s != "torso"]) - len(missing_optional), "total": total},
        "retargetable": not missing_required,
        "notes": notes,
    }


def _torso_sources(n: int) -> list[str]:
    """Quais juntas do SOMA alimentam uma coluna de ``n`` ossos (o ultimo e sempre o Chest)."""
    if n == 1:
        return ["Chest"]
    return ["Spine1"] + ["Spine2"] * (n - 2) + ["Chest"]


def _neck_sources(n: int) -> list[str]:
    return ["Neck1"] + ["Neck2"] * (n - 1)


def source_joint_names(bones: list[tuple[str, str | None]]) -> tuple[dict, dict[str, str]]:
    """Para um esqueleto que e a FONTE da animacao (FBX do Mixamo, BVH de captura).

    Devolve o mapeamento dele e ``{osso: junta do SOMA}``: por qual junta cada osso responde
    no retarget. Osso sem papel fica de fora e segue com o nome que tem.
    """
    mapping = build_mapping(bones)
    by_joint: dict[str, str] = {}
    for slot, bone in mapping["slots"].items():
        by_joint.setdefault(soma_joint_for_slot(slot), bone)
    chains = ((mapping["torso"], _torso_sources(len(mapping["torso"]))), (mapping["neck"], _neck_sources(len(mapping["neck"]))))
    for chain, joints in chains:
        for bone, joint in zip(chain, joints):
            by_joint.setdefault(joint, bone)  # numa coluna longa, so o primeiro osso de cada junta
    return mapping, {bone: joint for joint, bone in by_joint.items()}


def rename_to_soma(names: list[str], soma: dict[str, str]) -> list[str]:
    """Os nomes da fonte trocados pelos do SOMA. Osso sem papel que ja usava um nome do SOMA
    (o "Chest" de uma coluna de quatro ossos) cede o nome a quem responde por ele."""
    taken = set(soma.values())
    return [soma[n] if n in soma else (f"{n}_fonte" if n in taken else n) for n in names]


def build_plan(mapping: dict) -> list[dict]:
    """Lista ordenada (pai antes de filho) de ossos a animar.

    Cada item: ``bone`` (alvo), ``joint`` (SOMA), ``mode`` e ``base``.

    - ``root``: quadril; recebe so o alinhamento de direcao (para onde o personagem olha).
    - ``inherit``: usa a mesma correcao de descanso do osso ``base``.
    - ``align``: sobre a correcao de ``base``, gira para a direcao osso->``aim_bone``
      coincidir com a direcao junta->``aim_joint`` da fonte. E o que absorve
      A-pose vs T-pose nos bracos e pernas.

    Coluna, cabeca, pes e claviculas herdam do quadril de proposito: as duas poses
    de descanso estao em pe, entao descanso corresponde a descanso e a malha nao
    e deformada so para copiar a curvatura da coluna ou o angulo do pe da fonte.
    Mao e dedos herdam do antebraco, que e quem carrega a diferenca de A-pose.
    """
    slots = mapping["slots"]
    hips = slots["hips"]
    plan: list[dict] = [{"slot": "hips", "bone": hips, "joint": "Hips", "mode": "root", "base": None}]

    def inherit(slot: str, bone: str, joint: str, base: str) -> None:
        plan.append({"slot": slot, "bone": bone, "joint": joint, "mode": "inherit", "base": base})

    def align(slot: str, joint: str, base: str, aim_slot: str) -> str:
        """Devolve o osso cuja correcao os descendentes devem herdar."""
        bone = slots.get(slot)
        if bone is None:
            return base
        aim = slots.get(aim_slot)
        if aim is None:
            inherit(slot, bone, joint, base)
            return base
        plan.append(
            {
                "slot": slot,
                "bone": bone,
                "joint": joint,
                "mode": "align",
                "base": base,
                "aim_bone": aim,
                "aim_joint": soma_joint_for_slot(aim_slot),
            }
        )
        return bone

    for bone, joint in zip(mapping["torso"], _torso_sources(len(mapping["torso"]))):
        inherit("torso", bone, joint, hips)
    for bone, joint in zip(mapping["neck"], _neck_sources(len(mapping["neck"]))):
        inherit("neck", bone, joint, hips)
    if "head" in slots:
        inherit("head", slots["head"], "Head", hips)

    for s, _ in SIDES:
        if f"{s}_shoulder" in slots:
            inherit(f"{s}_shoulder", slots[f"{s}_shoulder"], soma_joint_for_slot(f"{s}_shoulder"), hips)
        base = align(f"{s}_arm", soma_joint_for_slot(f"{s}_arm"), hips, f"{s}_forearm")
        base = align(f"{s}_forearm", soma_joint_for_slot(f"{s}_forearm"), base, f"{s}_hand")
        hand_slots = [f"{s}_hand"] + [f"{s}_{f}{i}" for f in FINGERS for i in (1, 2, 3)]
        for slot in hand_slots:
            if slot in slots:
                inherit(slot, slots[slot], soma_joint_for_slot(slot), base)

        base = align(f"{s}_upleg", soma_joint_for_slot(f"{s}_upleg"), hips, f"{s}_leg")
        align(f"{s}_leg", soma_joint_for_slot(f"{s}_leg"), base, f"{s}_foot")
        for slot in (f"{s}_foot", f"{s}_toe"):
            if slot in slots:
                inherit(slot, slots[slot], soma_joint_for_slot(slot), hips)
    return plan
