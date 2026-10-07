"""Static seeded campus definition: buildings, zones, road graph, sensors.

Coordinates are world units on the XZ plane (X east, Z south).
"""

BUILDINGS = [
    dict(id="admin", code="ADMIN-A", name="Administration Block", type="ADMIN",
         description="Central administration, registry and council chambers.",
         capacity=420, occupancy=268,
         floors=3, position_x=-50, position_z=-35, size_x=40, size_z=24, height=12,
         latitude=6.52435, longitude=3.37918,
         color="#4f7cff", has_backup_power=True),
    dict(id="eng", code="ENG-B", name="Engineering Building", type="ACADEMIC",
         description="Teaching labs, lecture halls and faculty offices for engineering.",
         capacity=1200, occupancy=840,
         floors=4, position_x=0, position_z=-38, size_x=50, size_z=28, height=16,
         latitude=6.52461, longitude=3.37945,
         color="#f59e0b", has_backup_power=True),
    dict(id="cs", code="CS-C", name="Computer Science Building", type="ACADEMIC",
         description="Computing labs, lecture theatre and the campus server room.",
         capacity=900, occupancy=610,
         floors=3, position_x=55, position_z=-32, size_x=34, size_z=24, height=12,
         latitude=6.52448, longitude=3.37981,
         color="#14b8a6", has_backup_power=True),
    dict(id="lib", code="LIB-D", name="Central Library", type="LIBRARY",
         description="Reading halls, periodicals archive and study spaces.",
         capacity=800, occupancy=512,
         floors=3, position_x=-50, position_z=18, size_x=40, size_z=28, height=13,
         latitude=6.52411, longitude=3.37912,
         color="#8b5cf6", has_backup_power=False),
    dict(id="canteen", code="CAN-E", name="Canteen & Dining Hall", type="AMENITY",
         description="Dining hall, kitchen and dry storage for campus catering.",
         capacity=500, occupancy=305,
         floors=1, position_x=0, position_z=32, size_x=36, size_z=20, height=6,
         latitude=6.52398, longitude=3.37936,
         color="#ec4899", has_backup_power=False),
    dict(id="clinic", code="CLI-F", name="Campus Clinic", type="MEDICAL",
         description="Outpatient clinic with triage, treatment rooms and pharmacy.",
         capacity=120, occupancy=44,
         floors=1, position_x=52, position_z=20, size_x=26, size_z=18, height=6,
         latitude=6.52404, longitude=3.37974,
         color="#22c55e", has_backup_power=True),
]

BUILDINGS_BY_ID = {b["id"]: b for b in BUILDINGS}
BUILDINGS_BY_CODE = {b["code"]: b for b in BUILDINGS}


def build_floors() -> list[dict]:
    """Floor records for every building: id '{CODE}-F{n}' with 1-based floor numbers."""
    floors: list[dict] = []
    for b in BUILDINGS:
        area = round(b["size_x"] * b["size_z"] / max(1, b["floors"]), 1)
        zones = ZONE_TEMPLATES.get(b["id"], [])
        for n in range(1, b["floors"] + 1):
            floors.append(dict(
                id=f"{b['code']}-F{n}",
                building_id=b["id"],
                floor_number=n,
                name="Ground Floor" if n == 1 else f"Floor {n}",
                zone_count=sum(1 for t in zones if t[2] == n - 1),
                area_sqm=area,
                is_evacuation_level=(n == 1),
            ))
    return floors


def floor_id_for(building_id: str, floor_number_0based: int) -> str | None:
    b = BUILDINGS_BY_ID.get(building_id)
    if not b or not (0 <= floor_number_0based < b["floors"]):
        return None
    return f"{b['code']}-F{floor_number_0based + 1}"


def zone_dims(building_id: str) -> tuple[float, float, float]:
    """(width, depth, height) world units for a zone inside the given building."""
    b = BUILDINGS_BY_ID[building_id]
    return (
        round(b["size_x"] * 0.28, 2),
        round(b["size_z"] * 0.28, 2),
        round(b["height"] / max(1, b["floors"]), 2),
    )


ZONE_TEMPLATES = {
    "eng": [
        ("eng_ground", "Ground Floor Lobby", 0, 160, "LOBBY", [(0, "eng_electronics"), (0, "eng_lecture"), (0, "eng_stair")]),
        ("eng_electronics", "Electronics Lab", 0, 90, "LAB", [(0, "eng_ground"), (0, "eng_exit_s")]),
        ("eng_lecture", "Lecture Hall A", 0, 260, "LECTURE", [(0, "eng_ground"), (0, "eng_stair")]),
        ("eng_computer", "Computer Lab", 1, 220, "LAB", [(1, "eng_stair"), (1, "eng_faculty"), (1, "eng_exit_n")]),
        ("eng_faculty", "Faculty Area", 2, 110, "OFFICE", [(2, "eng_stair"), (2, "eng_computer")]),
        ("eng_stair", "Central Stairwell", 1, 80, "CORE", [(0, "eng_ground"), (0, "eng_lecture"), (1, "eng_computer"), (2, "eng_faculty"), (3, "eng_exit_n")]),
        ("eng_exit_s", "Emergency Exit South", 0, 120, "EXIT", [(0, "eng_electronics")]),
        ("eng_exit_n", "Emergency Exit North", 3, 120, "EXIT", [(1, "eng_computer"), (3, "eng_stair")]),
    ],
    "admin": [
        ("admin_ground", "Reception & Lobby", 0, 120, "LOBBY", [(0, "admin_offices"), (0, "admin_stair"), (0, "admin_exit")]),
        ("admin_offices", "Administrative Offices", 1, 180, "OFFICE", [(1, "admin_stair"), (1, "admin_council")]),
        ("admin_council", "Council Chamber", 2, 90, "LECTURE", [(2, "admin_stair")]),
        ("admin_stair", "Stairwell", 1, 60, "CORE", [(0, "admin_ground"), (1, "admin_offices"), (2, "admin_council")]),
        ("admin_exit", "Emergency Exit", 0, 100, "EXIT", [(0, "admin_ground")]),
    ],
    "cs": [
        ("cs_ground", "Ground Floor Lobby", 0, 140, "LOBBY", [(0, "cs_lab"), (0, "cs_stair"), (0, "cs_exit")]),
        ("cs_lab", "Computing Lab", 1, 240, "LAB", [(1, "cs_stair"), (1, "cs_lecture")]),
        ("cs_lecture", "Lecture Theatre B", 0, 200, "LECTURE", [(0, "cs_ground"), (1, "cs_lab")]),
        ("cs_stair", "Stairwell", 1, 60, "CORE", [(0, "cs_ground"), (1, "cs_lab")]),
        ("cs_exit", "Emergency Exit", 0, 100, "EXIT", [(0, "cs_ground")]),
    ],
    "lib": [
        ("lib_ground", "Circulation Desk", 0, 150, "LOBBY", [(0, "lib_reading"), (0, "lib_stair"), (0, "lib_exit")]),
        ("lib_reading", "Reading Hall", 1, 300, "STUDY", [(1, "lib_stair"), (1, "lib_archive")]),
        ("lib_archive", "Archive & Periodicals", 2, 120, "STUDY", [(2, "lib_stair")]),
        ("lib_stair", "Stairwell", 1, 60, "CORE", [(0, "lib_ground"), (1, "lib_reading"), (2, "lib_archive")]),
        ("lib_exit", "Emergency Exit", 0, 100, "EXIT", [(0, "lib_ground")]),
    ],
    "canteen": [
        ("canteen_dining", "Dining Hall", 0, 340, "DINING", [(0, "canteen_kitchen"), (0, "canteen_exit")]),
        ("canteen_kitchen", "Kitchen & Storage", 0, 80, "SERVICE", [(0, "canteen_dining")]),
        ("canteen_exit", "Emergency Exit", 0, 120, "EXIT", [(0, "canteen_dining")]),
    ],
    "clinic": [
        ("clinic_reception", "Reception", 0, 50, "LOBBY", [(0, "clinic_triage"), (0, "clinic_exit")]),
        ("clinic_triage", "Treatment Rooms", 0, 50, "MEDICAL", [(0, "clinic_reception")]),
        ("clinic_exit", "Emergency Exit", 0, 40, "EXIT", [(0, "clinic_reception")]),
    ],
}

ROAD_NODES = [
    dict(id="ring_sw", name="SW Junction", x=-78, z=52, kind="JUNCTION"),
    dict(id="ring_s_mid", name="South Gate Junction", x=0, z=52, kind="JUNCTION"),
    dict(id="ring_s2", name="Parking Junction", x=60, z=52, kind="JUNCTION"),
    dict(id="ring_se", name="SE Junction", x=78, z=52, kind="JUNCTION"),
    dict(id="road_w2", name="West Road South", x=-78, z=30, kind="JUNCTION"),
    dict(id="mid_w", name="West Mid Junction", x=-78, z=0, kind="JUNCTION"),
    dict(id="road_wn", name="West Road North", x=-78, z=-35, kind="JUNCTION"),
    dict(id="ring_nw", name="NW Junction", x=-78, z=-60, kind="JUNCTION"),
    dict(id="road_s2", name="South Road West", x=-27, z=52, kind="JUNCTION"),
    dict(id="court_w", name="Courtyard West", x=-27, z=0, kind="JUNCTION"),
    dict(id="court_wn", name="Courtyard West North", x=-27, z=-35, kind="JUNCTION"),
    dict(id="ring_n2", name="North Road West", x=-27, z=-60, kind="JUNCTION"),
    dict(id="court_c", name="Courtyard Center", x=0, z=0, kind="COURTYARD"),
    dict(id="court_cn", name="Courtyard North", x=0, z=-60, kind="JUNCTION"),
    dict(id="road_s3", name="South Road East", x=27, z=52, kind="JUNCTION"),
    dict(id="court_e", name="Courtyard East", x=27, z=0, kind="JUNCTION"),
    dict(id="court_en", name="Courtyard East North", x=27, z=-35, kind="JUNCTION"),
    dict(id="ring_n3", name="North Road East", x=27, z=-60, kind="JUNCTION"),
    dict(id="road_e2", name="East Road South", x=78, z=30, kind="JUNCTION"),
    dict(id="mid_e", name="East Mid Junction", x=78, z=0, kind="JUNCTION"),
    dict(id="road_en", name="East Road North", x=78, z=-35, kind="JUNCTION"),
    dict(id="ring_ne", name="NE Junction", x=78, z=-60, kind="JUNCTION"),
    dict(id="gate_main", name="Main Gate (Gate A)", x=0, z=68, kind="GATE", is_exit=True, exit_capacity=1.6),
    dict(id="gate_east", name="Emergency Gate (Gate C)", x=90, z=0, kind="GATE", is_exit=True, exit_capacity=1.2),
    dict(id="gate_west", name="Emergency Gate (Gate B)", x=-90, z=0, kind="GATE", is_exit=True, exit_capacity=1.0),
    dict(id="ex_admin", name="Admin East Exit", x=-29, z=-35, kind="EXIT"),
    dict(id="ex_admin_w", name="Admin West Exit", x=-70, z=-35, kind="EXIT"),
    dict(id="ex_eng_s", name="Engineering South Exit", x=0, z=-24, kind="EXIT"),
    dict(id="ex_eng_n", name="Engineering North Exit", x=0, z=-54, kind="EXIT"),
    dict(id="ex_cs", name="CS West Exit", x=38, z=-32, kind="EXIT"),
    dict(id="ex_lib", name="Library East Exit", x=-29, z=18, kind="EXIT"),
    dict(id="ex_canteen_s", name="Canteen South Exit", x=0, z=42, kind="EXIT"),
    dict(id="ex_canteen_n", name="Canteen North Exit", x=0, z=22, kind="EXIT"),
    dict(id="ex_clinic", name="Clinic West Exit", x=38, z=20, kind="EXIT"),
    dict(id="node_parking", name="Parking Bay", x=60, z=45, kind="PARKING"),
]

_ROAD = dict


def _r(rid, name, a, b, kind="INTERNAL"):
    return dict(id=rid, name=name, from_node=a, to_node=b, kind=kind)


ROADS = [
    _r("r_sw_s2", "South Ring Road (W)", "ring_sw", "road_s2"),
    _r("r_s2_gate", "South Ring Road (Gate)", "road_s2", "ring_s_mid"),
    _r("r_gate_s3", "South Ring Road (Gate E)", "ring_s_mid", "road_s3"),
    _r("r_s3_s2p", "South Ring Road (Parking)", "road_s3", "ring_s2"),
    _r("r_s2p_se", "South Ring Road (E)", "ring_s2", "ring_se"),
    _r("r_w_s2", "West Ring Road (S)", "ring_sw", "road_w2"),
    _r("r_w2_mid", "West Ring Road", "road_w2", "mid_w"),
    _r("r_mid_wn", "West Ring Road (N)", "mid_w", "road_wn"),
    _r("r_wn_nw", "West Ring Road (NW)", "road_wn", "ring_nw"),
    _r("r_e_s2", "East Ring Road (S)", "ring_se", "road_e2"),
    _r("r_e2_mid", "East Ring Road", "road_e2", "mid_e"),
    _r("r_mid_en", "East Ring Road (N)", "mid_e", "road_en"),
    _r("r_en_ne", "East Ring Road (NE)", "road_en", "ring_ne"),
    _r("r_nw_n2", "North Ring Road (W)", "ring_nw", "ring_n2"),
    _r("r_n2_cn", "North Ring Road (Gate N)", "ring_n2", "court_cn"),
    _r("r_cn_n3", "North Ring Road (Gate N E)", "court_cn", "ring_n3"),
    _r("r_n3_ne", "North Ring Road (E)", "ring_n3", "ring_ne"),
    _r("r_mid_w_cw", "Courtyard Road (W)", "mid_w", "court_w"),
    _r("r_cw_cc", "Courtyard Road (SW)", "court_w", "court_c"),
    _r("r_cc_ce", "Courtyard Road (SE)", "court_c", "court_e"),
    _r("r_ce_me", "Courtyard Road (E)", "court_e", "mid_e"),
    _r("r_s2_cw", "West Connector North", "road_s2", "court_w"),
    _r("r_cw_wn", "West Connector Upper", "court_w", "court_wn"),
    _r("r_wn_n2", "West Connector North Exit", "court_wn", "ring_n2"),
    _r("r_s3_ce", "East Connector North", "road_s3", "court_e"),
    _r("r_ce_en", "East Connector Upper", "court_e", "court_en"),
    _r("r_en_n3", "East Connector North Exit", "court_en", "ring_n3"),
    _r("r_gate_spur", "Main Gate Approach", "gate_main", "ring_s_mid"),
    _r("r_gate_e", "East Emergency Gate Approach", "gate_east", "mid_e"),
    _r("r_gate_w", "West Emergency Gate Approach", "gate_west", "mid_w"),
    _r("r_admin_e", "Admin East Access", "ex_admin", "court_wn"),
    _r("r_admin_w", "Admin West Access", "ex_admin_w", "road_wn"),
    _r("r_eng_s", "Engineering South Access", "ex_eng_s", "court_c"),
    _r("r_eng_n", "Engineering North Access", "ex_eng_n", "court_cn"),
    _r("r_cs_w", "CS West Access", "ex_cs", "court_en"),
    _r("r_lib_e", "Library East Access", "ex_lib", "court_w"),
    _r("r_cant_s", "Canteen South Access", "ex_canteen_s", "ring_s_mid"),
    _r("r_cant_n", "Canteen North Access", "ex_canteen_n", "court_c"),
    _r("r_clinic_w", "Clinic West Access", "ex_clinic", "court_e"),
    _r("r_parking", "Parking Access", "node_parking", "ring_s2"),
]

# Building id -> evacuation origin node (start of every route)
BUILDING_EXITS = {
    "admin": ["ex_admin", "ex_admin_w"],
    "eng": ["ex_eng_s", "ex_eng_n"],
    "cs": ["ex_cs"],
    "lib": ["ex_lib"],
    "canteen": ["ex_canteen_s", "ex_canteen_n"],
    "clinic": ["ex_clinic"],
}

SENSOR_TYPES = {
    "occupancy": ("OCC", "%", 0, 100),
    "temperature": ("TEMP", "°C", 10, 60),
    "humidity": ("HUM", "%", 15, 95),
    "energy": ("PWR", "kW", 0, 400),
    "water": ("WTR", "L/min", 0, 120),
    "smoke": ("SMK", "ppm", 0, 500),
    "air_quality": ("AQI", "AQI", 0, 300),
    "traffic": ("TRF", "veh/min", 0, 40),
    "parking": ("PRK", "%", 0, 100),
}

# Normal operating thresholds used for anomaly detection (distinct from device range).
NORMAL_RANGES: dict[str, tuple[float, float]] = {
    "occupancy": (0.0, 90.0),
    "temperature": (18.0, 30.0),
    "humidity": (30.0, 70.0),
    "energy": (0.0, 300.0),
    "water": (0.0, 80.0),
    "smoke": (0.0, 10.0),
    "air_quality": (0.0, 100.0),
    "traffic": (0.0, 20.0),
    "parking": (0.0, 90.0),
}

# Fixed per-type suffix for building sensors: ENG-B-TEMP-01, ENG-B-HUM-02, …
_BUILDING_CODE_SEQ = {"temperature": 1, "humidity": 2, "energy": 3,
                      "smoke": 4, "air_quality": 5, "occupancy": 6}


def sensor_code_for(stype: str, building_code: str | None, seq: int | None = None) -> str:
    abbrev = SENSOR_TYPES[stype][0]
    if building_code:
        n = _BUILDING_CODE_SEQ.get(stype, seq or 1)
        return f"{building_code}-{abbrev}-{n:02d}"
    return f"CAMPUS-{abbrev}-{(seq or 1):02d}"


def build_sensors() -> list[dict]:
    sensors: list[dict] = []
    for b in BUILDINGS:
        bx, bz = b["position_x"], b["position_z"]
        zones = [t for t in ZONE_TEMPLATES.get(b["id"], []) if t[4] != "EXIT"]
        for idx, stype in enumerate(["occupancy", "temperature", "energy", "smoke", "air_quality", "humidity"]):
            code, unit, vmin, vmax = SENSOR_TYPES[stype]
            nmin, nmax = NORMAL_RANGES[stype]
            sensors.append(
                dict(
                    id=f"{stype}_{b['id']}",
                    sensor_code=sensor_code_for(stype, b["code"]),
                    name=f"{code}-{b['name']}",
                    type=stype,
                    building_id=b["id"],
                    zone_id=zones[idx % len(zones)][0] if zones else None,
                    unit=unit,
                    status="ONLINE",
                    x=bx + (idx % 3 - 1) * b["size_x"] * 0.3,
                    y=round(b["height"] * 0.15, 2),
                    z=bz + (idx // 3 - 0.5) * b["size_z"] * 0.4,
                    min_value=float(vmin),
                    max_value=float(vmax),
                    normal_min=nmin,
                    normal_max=nmax,
                    healthy=True,
                )
            )
    campus_seq: dict[str, int] = {}
    for rid, node in [("ring_s_mid", "gate_main"), ("mid_e", "gate_east"), ("road_s3", "ring_s2"),
                      ("court_w", "mid_w"), ("court_cn", "ring_n2")]:
        n = next(nd for nd in ROAD_NODES if nd["id"] == rid)
        campus_seq["traffic"] = campus_seq.get("traffic", 0) + 1
        _, unit, vmin, vmax = SENSOR_TYPES["traffic"]
        nmin, nmax = NORMAL_RANGES["traffic"]
        sensors.append(dict(id=f"traffic_{rid}", sensor_code=sensor_code_for("traffic", None, campus_seq["traffic"]),
                            name=f"TRF-{n['name']}", type="traffic", building_id=None, node_id=rid,
                            zone_id=None, unit=unit, status="ONLINE",
                            x=n["x"], y=1.5, z=n["z"],
                            min_value=float(vmin), max_value=float(vmax),
                            normal_min=nmin, normal_max=nmax, healthy=True))
    campus_extra = [
        dict(id="parking_main", type="parking", name="PRK-Main Parking", building_id=None,
             unit="%", x=60, y=0.0, z=45),
        dict(id="water_campus", type="water", name="WTR-Campus Main", building_id=None,
             unit="L/min", x=0, y=0.5, z=10),
        dict(id="temp_outdoor", type="temperature", name="TEMP-Ambient", building_id=None,
             unit="°C", x=-15, y=2.0, z=8),
    ]
    for s in campus_extra:
        campus_seq[s["type"]] = campus_seq.get(s["type"], 0) + 1
        _, _, vmin, vmax = SENSOR_TYPES[s["type"]]
        nmin, nmax = NORMAL_RANGES[s["type"]]
        sensors.append(dict(**s, sensor_code=sensor_code_for(s["type"], None, campus_seq[s["type"]]),
                            status="ONLINE", zone_id=None,
                            min_value=float(vmin), max_value=float(vmax),
                            normal_min=nmin, normal_max=nmax, healthy=True))
    return sensors


# Building adjacency for zone placement inside 3D footprint (relative offsets in 0..1)
ZONE_LAYOUT_HINT = True
