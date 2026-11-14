import asyncio
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import pygame as pg


WIDTH, HEIGHT = 960, 540
STEP = 1 / 120
GRAVITY = 1080
RESTITUTION = 0.86
MAX_TILT = 28
TILT_SPEED = 18
TIP_HALF_WIDTH = 8
SPRING_RANGE = 46
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
SOUND_FILES = {
    "bounce": "idle bounce",
    "stomp": "attack bounce",
    "pickup": "cracking",
    "hurt": "slime impact",
    "win": "alarm reverberation",
    "blast": "massive explosion",
    "charge": "slime sounds",
    "wave": "bomb explosion",
}
FULL, LOW = 100, 20
ENEMY_DAMAGE, MIN_HEALTH = 15, 5
WAVE_RADIUS = 390


def frame(name, region, size, green_screen=False):
    try:
        image = pg.image.load(str(ASSETS / name)).convert_alpha()
    except (pg.error, OSError):
        return None
    if region:
        image = image.subsurface(pg.Rect(region).clip(image.get_rect())).copy()
    keyed = pg.Surface(image.get_size(), pg.SRCALPHA)
    for y in range(image.get_height()):
        for x in range(image.get_width()):
            r, g, b, a = image.get_at((x, y))
            background = (g > 100 and g > 1.5 * max(r, b)) if green_screen else max(r, g, b) < 12
            if a and not background:
                keyed.set_at((x, y), (r, g, b, a))
    bounds = keyed.get_bounding_rect()
    return pg.transform.scale(keyed.subsurface(bounds), size) if bounds else None


class Art:
    def __init__(self):
        self.pogo = frame("POGO_SPRITES.png", None, (29, 40))
        self.spring = frame("POGO_SPRIE_SPRING.png", None, (10, 15))
        self.rider = frame("SLIMY_SPRITES.png", (297, 0, 60, 95), (29, 48))
        self.slimy = frame("SLIMY_SPRITES.png", (7, 10, 80, 77), (77, 70))
        self.friend = frame("FRIEND_SPRITES.png", (80, 30, 112, 212), (50, 92))
        self.friend_pogo = frame("FRIEND_HOLDING_XPOGO_SPRITES.png", (70, 24, 110, 182), (56, 92))
        self.hand = frame("SEVERED_HAND_SPRITES.png", (0, 90, 135, 105), (57, 53))
        self.boss = [frame("TUTORIAL_BOSS_SPRITES.png", (i * 95 + 5, 70, 86, 85),
                           (121, 79)) for i in range(7)]
        self.healthbar = pg.image.load(str(ASSETS / "PLAYER_HEALTHBAR.jpg")).convert()
        self.healthbar.set_colorkey((255, 255, 255))
        self.healthbar = pg.transform.scale(self.healthbar.subsurface((22, 165, 1238, 225)),
                                            (223, 40))
        self.patrols = [
            [frame("ENEMY_SOLDIER_SPRITES.png", (200 + i * 183, 430, 126, 151),
                   (30, 46)) for i in range(4)],
            [frame("VIOLETGUY_SPRITES.png", (200 * i, 457, 200, 234),
                   (29, 51), green_screen=True) for i in range(3)],
        ]
        self.sounds = {}
        if pg.mixer.get_init():
            extension = ".ogg" if sys.platform == "emscripten" else ".mp3"
            for event, filename in SOUND_FILES.items():
                try:
                    sound = pg.mixer.Sound(str(ASSETS / "SFXs" / (filename + extension)))
                    sound.set_volume(0.35)
                    self.sounds[event] = sound
                except (pg.error, OSError):
                    pass

    def play(self, event):
        if event in self.sounds:
            self.sounds[event].play()

    def draw_rider(self, screen, player, camera):
        sprite = pg.Surface((180, 180), pg.SRCALPHA)
        if self.rider:
            sprite.blit(self.rider, (75, 11))
        else:
            pg.draw.rect(sprite, "#182a36", (79, 37, 22, 19))
            pg.draw.rect(sprite, "#57e78a", (78, 14, 24, 23))
            pg.draw.rect(sprite, "#2cab68", (78, 31, 24, 6))
            for x in (83, 95):
                pg.draw.rect(sprite, "#102833", (x, 20, 4, 6))
            pg.draw.rect(sprite, "#0d2732", (83, 46, 5, 13))
            pg.draw.rect(sprite, "#0d2732", (94, 46, 5, 13))
        if self.pogo:
            sprite.blit(self.pogo, (76, 43))
        else:
            pg.draw.rect(sprite, "#ffc04b", (88, 47, 4, 36))
            pg.draw.rect(sprite, "#ffcf66", (77, 45, 26, 4))
            pg.draw.rect(sprite, "#ffcf66", (81, 66, 18, 4))
        spring_height = 5 + round(10 * (1 - player.compression))
        if self.spring:
            sprite.blit(pg.transform.scale(self.spring, (10, spring_height)),
                        (85, 89 - spring_height))
        else:
            points = [(86 + i % 2 * 8, 89 - spring_height + i * spring_height / 5)
                      for i in range(6)]
            pg.draw.lines(sprite, "#d3e9ee", False, points, 2)
        pg.draw.rect(sprite, "#6d8af3", (83, 86, 14, 4))
        rotated = pg.transform.rotate(sprite, -player.tilt)
        screen.blit(rotated, rotated.get_rect(center=(round(player.x - camera.x),
                                                      round(player.y - camera.y))))


class Pogo:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.vx = self.vy = self.tilt = self.compression = 0.0
        self.hp = FULL

    def overlaps(self, platform, x):
        return x + TIP_HALF_WIDTH > platform.left and x - TIP_HALF_WIDTH < platform.right

    def bounce(self):
        minimum = 492 + (FULL - self.hp) * 5.7
        speed = min(minimum + 70, max(self.vy * RESTITUTION, minimum))
        angle = math.radians(self.tilt)
        self.vx = math.sin(angle) * speed
        self.vy = -math.cos(angle) * speed
        self.compression = 1

    def step(self, direction, dt, platforms, width, braking=False, charging=False):
        tilt_speed = TILT_SPEED * (0.42 if charging else 1)
        self.tilt += (direction * MAX_TILT - self.tilt) * (1 - math.exp(-tilt_speed * dt))
        if braking:
            self.vx *= math.exp(-10 * dt)
        elif direction:
            cap = 230 + (FULL - self.hp) * 1.3
            target = direction * cap * (0.4 if charging else 1)
            self.vx += (target - self.vx) * (1 - math.exp(-(6 if charging else 2.4) * dt))
        elif charging:
            self.vx *= math.exp(-6 * dt)
        old_x, old_y = self.x, self.y
        self.vy += GRAVITY * dt
        self.x = max(18, min(width - 18, self.x + self.vx * dt))
        self.y += self.vy * dt
        if self.vy > 0:
            # Sweep the tip's footprint to the next position to catch thin edges.
            for platform in platforms:
                if old_y <= platform.top <= self.y:
                    fraction = (platform.top - old_y) / (self.y - old_y)
                    impact_x = old_x + (self.x - old_x) * fraction
                    if self.overlaps(platform, impact_x):
                        self.x, self.y = impact_x, platform.top
                        self.bounce()
                        return platform
        if self.vy >= 0:
            gap = min((p.top - self.y for p in platforms
                       if p.top >= self.y and self.overlaps(p, self.x)), default=SPRING_RANGE)
            self.compression = max(0, 1 - gap / SPRING_RANGE)
        else:
            self.compression = max(0, self.compression - dt * 15)
        return None

    @property
    def body(self):
        lean = math.sin(math.radians(self.tilt))
        return pg.Rect(round(self.x + lean * 44) - 13, round(self.y) - 71, 26, 47)


class Patrol:
    def __init__(self, left, right, ground, kind):
        self.left, self.right, self.ground, self.kind = left, right, ground, kind
        self.x, self.facing = float(left), 1
        self.active = True

    @property
    def body(self):
        return pg.Rect(round(self.x) - 14, self.ground - 42, 28, 42)

    def step(self, dt):
        self.x += self.facing * (63 + 12 * self.kind) * dt
        if self.x >= self.right or self.x <= self.left:
            self.x = max(self.left, min(self.right, self.x))
            self.facing *= -1

    def draw(self, screen, art, camera, time):
        frames = art.patrols[self.kind]
        image = frames[int(time * 9) % len(frames)]
        x = round(self.x - camera.x)
        ground = round(self.ground - camera.y)
        if image:
            if self.facing < 0:
                image = pg.transform.flip(image, True, False)
            screen.blit(image, image.get_rect(midbottom=(x, ground)))
            return
        y = ground
        color = ("#56618c", "#9f52c9")[self.kind]
        pg.draw.rect(screen, color, (x - 12, y - 45, 24, 18))
        pg.draw.rect(screen, "#92fff7", (x + self.facing * 5 - 5, y - 40, 10, 5))
        pg.draw.rect(screen, color, (x - 10, y - 25, 20, 13))
        stride = int(time * 9) % 2 * 4
        pg.draw.rect(screen, "#618d9c", (x - 10, y - 12, 7, 12 - stride))
        pg.draw.rect(screen, "#618d9c", (x + 3, y - 12, 7, 8 + stride))




@dataclass(frozen=True)
class Level:
    name: str
    color: str
    route: tuple
    stations: dict
    seals: tuple
    patrols: tuple
    full_exit: bool = False
    boss: bool = False


# Platform entries are left edge, elevation, and width. Stations are tied to
# platform indices, so checkpoints and interactables share the same geometry.
LEVELS = (
    Level("Cell Block", "#82eac1", (
        (0, 1340, 310), (300, 1272, 270), (530, 1057, 310),
        (800, 980, 305), (1090, 910, 290),
    ), {1: "drain", 3: "heal"}, (), (2,), True),
    Level("Lockdown", "#ffa772", (
        (0, 1520, 300), (245, 1455, 300), (490, 1217, 312),
        (755, 1140, 305), (1015, 902, 305), (1280, 826, 290),
    ), {1: "heal", 3: "heal", 5: "heal"}, (1, 3), (1, 2, 3), True),
    Level("The Spillway", "#6ce8ff", (
        (0, 1740, 336), (294, 1480, 308), (526, 1220, 304),
        (305, 968, 287), (541, 717, 300), (801, 647, 300),
    ), {0: "drain", 2: "drain", 4: "heal"}, (), (1, 3, 4), True),
    Level("Pressure Towers", "#c7a0ff", (
        (0, 1830, 330), (288, 1760, 302), (550, 1525, 294),
        (806, 1282, 313), (1078, 1211, 287), (1305, 958, 309),
        (1570, 710, 295),
    ), {1: "heal", 4: "heal", 6: "heal"}, (1, 4), (1, 2, 4, 5), True),
    Level("Containment Core", "#f88fc5", (
        (0, 1690, 350), (313, 1620, 448), (592, 1391, 362),
        (976, 1100, 320), (1240, 858, 365),
    ), {1: "heal", 4: "heal"}, (), (2, 3), True, True),
)

INTRO = (
    ("Friend", "Hey... I brought the Xpogo you asked for. Is it still for your son?"),
    ("Friend", "They told him you're on a secret mission. A thrilling adventure."),
    ("Friend", "After the incident, I thought the treatment would save you. I didn't know what it would cost."),
    ("Slimy", "I still get to hope. For my son. For you. That's something."),
    ("Friend", "I've got the escape plans. Security is light tomorrow. Just be caref—"),
)
BRIEFINGS = (
    "Find the Xpogo. The violet vent sheds mass so you can reach the high ledge.",
    "Land on each orange relay deck. At full health, Space charges a shockwave that breaks its relay.",
    "Climb the shaft at low health. The third ledge doubles back to the left.",
    "Break both relays. Use the green stations to refill between shockwaves.",
    "The containment slime takes three shockwaves. Refill on its deck between hits.",
)


class Game:
    def __init__(self, art):
        self.art = art
        self.rng = random.Random(18)
        self.reset()

    def reset(self):
        self.deaths = 0
        self.load(0)
        self.state = "intro"
        self.line = 0

    def load(self, number):
        self.number = number
        self.level = LEVELS[number]
        self.route = [pg.Rect(x, y, w, 25) for x, y, w in self.level.route]
        self.platforms = sorted(self.route, key=lambda rect: rect.top)
        self.width = max(p.right for p in self.route) + 35
        self.floor = self.route[0].y
        self.ceiling = min(p.y for p in self.route) - 410
        last = self.route[-1]
        self.gate = pg.Rect(last.centerx + 15, last.y - 93, 54, 93)
        self.checkpoint = 0
        self.saved_hp = FULL
        self.player = Pogo(105, self.floor - 22)
        self.camera = pg.Vector2(0, self.floor - 399)
        self.patrols = [Patrol(self.route[i].left + 72, self.route[i].right - 26,
                               self.route[i].y, n % 2) for n, i in enumerate(self.level.patrols)]
        self.seals = set(self.level.seals)
        self.boss_hp = 3 if self.level.boss else 0
        self.pulses = []
        self.particles = []
        self.equipped = number > 0
        self.last_platform = 0
        self.time = self.state_time = self.immunity = self.charge = 0.0
        self.shake = self.flash = 0.0
        self.wave, self.boss_hit = None, False
        self.message, self.message_time = "", 0
        self.state = "briefing"

    def note(self, message):
        self.message, self.message_time = message, 2.5

    def advance(self):
        if self.state == "intro":
            self.line += 1
            self.state_time = 0
            if self.line == len(INTRO):
                self.state = "blackout"
                self.art.play("blast")
        elif self.state == "briefing":
            self.state = "play"
        elif self.state == "clear":
            if self.number + 1 == len(LEVELS):
                self.state = "ending"
            else:
                self.load(self.number + 1)
        elif self.state == "ending":
            self.reset()

    def respawn(self):
        if self.state != "play":
            return
        self.deaths += 1
        platform = self.route[self.checkpoint]
        self.player = Pogo(platform.left + min(105, platform.w // 2), platform.y - 24)
        self.player.hp = self.saved_hp
        self.last_platform = self.checkpoint
        self.camera.y = max(self.ceiling, platform.y - 395)
        self.immunity, self.charge = 2.2, 0
        self.wave = None
        self.note("Checkpoint restored")
        self.art.play("hurt")

    def station(self):
        # Interact anywhere above the last deck within one normal jump.
        deck = self.route[self.last_platform]
        if deck.left <= self.player.x <= deck.right and -8 <= deck.y - self.player.y <= 165:
            return self.level.stations.get(self.last_platform)
        return None

    def interact(self):
        if self.state != "play":
            return
        if not self.equipped:
            if abs(self.player.x - 211) <= 62:
                self.equipped = True
                self.art.play("pickup")
                self.note("Xpogo equipped. A / D to tilt, hold Shift to brake.")
            return
        station = self.station()
        if not station:
            self.note("Move over a green station or violet vent")
            return
        if self.charge or self.wave:
            return
        self.player.hp = FULL if station == "heal" else LOW
        self.saved_hp = self.player.hp
        self.burst(self.player.x, self.player.y - 33, "#90ffbe" if station == "heal" else "#d69cff", 18)
        self.note("Full mass restored" if station == "heal" else "Mass vented. Your next bounce goes higher.")
        self.art.play("pickup")

    def attack(self):
        if self.state != "play" or not self.equipped or self.charge or self.wave:
            return
        if self.player.hp != FULL:
            self.note("Shockwave requires 100% health")
            return
        self.charge = 0.39
        self.art.play("charge")

    def hurt(self):
        if self.immunity or self.charge:
            return
        self.player.hp = max(MIN_HEALTH, self.player.hp - ENEMY_DAMAGE)
        self.immunity = 1.1
        self.shake, self.flash = 8, 0.14
        self.art.play("hurt")

    def burst(self, x, y, color, amount):
        for _ in range(amount):
            direction = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(55, 305)
            life = self.rng.uniform(0.22, 0.65)
            self.particles.append([x, y, math.cos(direction) * speed, math.sin(direction) * speed,
                                   life, color])

    def seal_position(self, index):
        deck = self.route[index]
        return deck.centerx + 75, deck.y - 43

    def boss_position(self):
        return 639 + 29 * math.sin(self.time * 2.7), 1583 + 11 * math.sin(self.time * 5)

    def update_wave(self, dt):
        if self.charge:
            self.charge = max(0, self.charge - dt)
            if not self.charge:
                p = self.player
                p.hp, self.immunity = LOW, 0.85
                self.wave = (p.x, p.y - 30, 0.0)
                self.shake, self.flash = 20, 0.22
                self.burst(p.x, p.y - 30, "#fef2ae", 46)
                self.art.play("wave")
                self.note("Health spent. Use your higher bounce to climb.")
        if self.wave is None:
            return
        x, y, old_radius = self.wave
        radius = min(WAVE_RADIUS, old_radius + dt * 910)

        def reached(tx, ty):
            distance = math.hypot(tx - x, ty - y)
            return distance <= radius

        for index in tuple(self.seals):
            tx, ty = self.seal_position(index)
            if reached(tx, ty):
                self.seals.remove(index)
                self.burst(tx, ty, "#ffb06f", 24)
                self.note("Relay shattered")
        for enemy in self.patrols:
            if enemy.active and reached(*enemy.body.center):
                enemy.active = False
                self.burst(*enemy.body.center, "#77ffe6", 15)
        # Track boss contact per wave since its center can move across the ring twice.
        if self.boss_hp and not self.boss_hit and reached(*self.boss_position()):
            self.boss_hit = True
            self.boss_hp -= 1
            self.pulses.clear()
            self.burst(*self.boss_position(), "#8fffea", 38)
            self.note(f"Core exposed. {self.boss_hp} hits left." if self.boss_hp else "Containment slime defeated")
        if radius >= WAVE_RADIUS:
            self.wave, self.boss_hit = None, False
        else:
            self.wave = (x, y, radius)

    def gate_requirement(self):
        if self.boss_hp:
            return "Defeat the containment slime"
        if self.seals:
            return f"Break {len(self.seals)} shockwave relay(s)"
        if self.level.full_exit and self.player.hp != FULL:
            return "Airlock requires full health"
        return ""

    def step(self, direction, dt, braking=False):
        self.state_time += dt
        if self.state == "blackout":
            if self.state_time >= 1.15:
                self.state = "briefing"
            return
        if self.state != "play":
            return
        self.time += dt
        self.message_time = max(0, self.message_time - dt)
        self.immunity = max(0, self.immunity - dt)
        self.shake = max(0, self.shake - dt * 46)
        self.flash = max(0, self.flash - dt)
        p = self.player
        for particle in self.particles:
            particle[0] += particle[2] * dt
            particle[1] += particle[3] * dt
            particle[3] += 350 * dt
            particle[4] -= dt
        self.particles = [particle for particle in self.particles if particle[4] > 0]
        if not self.equipped:
            p.y = self.floor
            p.x = max(28, min(259, p.x + direction * 150 * dt))
            return
        previous_tip = p.y
        if self.wave is None:
            self.boss_hit = False
        self.update_wave(dt)
        deck = p.step(direction, dt, self.platforms, self.width, braking, bool(self.charge))
        if deck is not None:
            self.last_platform = self.route.index(deck)
            if self.last_platform > self.checkpoint:
                self.checkpoint, self.saved_hp = self.last_platform, p.hp
            self.art.play("bounce")
            self.burst(p.x, p.y, self.level.color, 8 if p.hp == FULL else 15)
            self.shake = max(self.shake, 2 if p.hp == FULL else 4)
        for enemy in self.patrols:
            if not enemy.active:
                continue
            enemy.step(dt)
            body = enemy.body
            if previous_tip < body.top <= p.y and body.left - 8 <= p.x <= body.right + 8:
                enemy.active = False
                p.y = body.top
                p.bounce()
                self.burst(*body.center, "#77ffe6", 14)
                self.art.play("stomp")
            elif body.colliderect(p.body):
                self.hurt()
        if self.boss_hp:
            bx, by = self.boss_position()
            if int((self.time - dt) / 1.9) != int(self.time / 1.9):
                vx = -215 if p.x < bx else 215
                self.pulses.append((bx, by + 10, vx, 2.2))
            self.pulses = [(x + vx * dt, y, vx, life - dt)
                           for x, y, vx, life in self.pulses if life > dt]
            if pg.Rect(bx - 49, by - 35, 98, 66).colliderect(p.body) or any(
                p.body.collidepoint(x, y) for x, y, _, _ in self.pulses
            ):
                self.hurt()
        if self.player is not p:
            return
        if p.y > self.floor + 205:
            self.respawn()
            return
        if self.gate.colliderect(p.body) and not self.gate_requirement():
            self.art.play("win")
            self.state = "clear"
        target_x = max(0, min(self.width - WIDTH, p.x - WIDTH * 0.49))
        target_y = max(self.ceiling, min(self.floor - 395, p.y - HEIGHT * 0.56))
        self.camera += (pg.Vector2(target_x, target_y) - self.camera) * (1 - math.exp(-6 * dt))


class View:
    def __init__(self):
        self.font = pg.font.SysFont("consolas", 19)
        self.small = pg.font.SysFont("consolas", 15, bold=True)
        self.heading = pg.font.SysFont("consolas", 30, bold=True)
        self.title = pg.font.SysFont("consolas", 52, bold=True)
        self.sky = pg.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / HEIGHT
            pg.draw.line(self.sky, (int(12 + 13 * t), int(13 + 12 * t), int(25 + 25 * t)),
                         (0, y), (WIDTH, y))
        self.overlay = pg.Surface((WIDTH, HEIGHT), pg.SRCALPHA)

    def label(self, screen, text, x, y, color="#e6ecfa", font=None):
        screen.blit((font or self.small).render(text, True, color), (x, y))

    def wrap(self, screen, text, x, y, width):
        line = ""
        for word in text.split():
            proposed = (line + " " + word).strip()
            if self.font.size(proposed)[0] > width:
                self.label(screen, line, x, y, font=self.font)
                y += 25
                line = word
            else:
                line = proposed
        self.label(screen, line, x, y, font=self.font)

    def dim(self, screen, color):
        self.overlay.fill(color)
        screen.blit(self.overlay, (0, 0))

    def panel(self, screen, rect, color):
        pg.draw.rect(screen, "#101525", rect, border_radius=6)
        pg.draw.rect(screen, color, rect, width=2, border_radius=6)

    def portrait(self, screen, sprite, x, y):
        if sprite:
            screen.blit(sprite, sprite.get_rect(midbottom=(x, y)))

    def intro(self, screen, game):
        pan = min(1, (game.line + game.state_time * 0.7) / 3)
        x = round(450 - 62 * pan)
        pg.draw.rect(screen, "#222c42", (0, 320, WIDTH, 53))
        pg.draw.line(screen, "#638193", (0, 320), (WIDTH, 320), 3)
        for bar_x in range(x + 55, x + 145, 17):
            pg.draw.rect(screen, "#465770", (bar_x, 99, 6, 222))
        pg.draw.line(screen, "#465770", (x + 48, 102), (x + 147, 102), 5)
        self.portrait(screen, game.art.slimy, x - 75, 319)
        self.portrait(screen, game.art.friend if game.line == 0 else game.art.friend_pogo,
                      x + 208, 319)
        self.label(screen, "PROTOPLASM", 45, 34, "#82eac1", self.heading)
        self.label(screen, "LAB CELL   /   NIGHT", 46, 74, "#9caec6")
        name, line = INTRO[game.line]
        color = "#83efc4" if name == "Slimy" else "#ffb37e"
        self.panel(screen, (36, 364, 888, 142), color)
        self.label(screen, name.upper(), 62, 381, color, self.heading)
        visible = line[:int(game.state_time * 56)]
        self.wrap(screen, visible, 64, 423, 820)
        self.label(screen, "ENTER  Continue     TAB  Skip", 640, 477, "#aebed5")

    def draw_world(self, screen, game, camera):
        color = game.level.color
        for x in range(-round(camera.x * 0.42) % 92, WIDTH, 92):
            pg.draw.rect(screen, "#20273d", (x, 0, 4, HEIGHT))
            for y in range(-round(camera.y * 0.5) % 68, HEIGHT, 68):
                pg.draw.rect(screen, "#333c55", (x + 12, y + 12, 14, 3))
        for y in range(-round(camera.y * 0.52) % 112, HEIGHT, 112):
            pg.draw.line(screen, "#252d43", (0, y), (WIDTH, y))
        offset = (-round(camera.x), -round(camera.y))
        for i, deck in enumerate(game.route):
            r = deck.move(offset)
            if not r.inflate(0, 155).colliderect(screen.get_rect()):
                continue
            pg.draw.rect(screen, "#242b43", r)
            pg.draw.rect(screen, color, (r.x, r.y, r.w, 3))
            for x in range(r.left + 10, r.right - 8, 22):
                pg.draw.rect(screen, "#505876", (x, r.y + 10, 8, 3))
            if i == game.checkpoint:
                pg.draw.circle(screen, color, (r.left + 13, r.top - 8), 4)
            station = game.level.stations.get(i)
            if station:
                accent = "#8cffad" if station == "heal" else "#ca99ff"
                station_x = r.left + 74
                pg.draw.rect(screen, accent, (station_x - 17, r.top - 12, 34, 8))
                for spark in range(3):
                    height = (game.time * 48 + spark * 12) % 36
                    pg.draw.circle(screen, accent, (station_x - 10 + spark * 10,
                                                     round(r.top - 14 - height)), 2)
                self.label(screen, "E  REFILL" if station == "heal" else "E  VENT",
                           r.left + 26, r.top - 58, accent)
        for i in game.seals:
            x, y = game.seal_position(i)
            x, y = round(x - camera.x), round(y - camera.y)
            pg.draw.rect(screen, "#682f41", (x - 18, y - 29, 36, 72))
            pg.draw.rect(screen, "#ffb06f", (x - 18, y - 29, 36, 72), 3)
            pg.draw.circle(screen, "#ffb06f", (x, y), 8, 2)
            self.label(screen, "RELAY", x - 23, y - 51, "#ffb06f")
        gate = game.gate.move(offset)
        locked = game.gate_requirement()
        gate_color = "#f79584" if locked else "#82ffbd"
        self.panel(screen, gate, gate_color)
        pg.draw.line(screen, gate_color, (gate.centerx, gate.y + 7),
                     (gate.centerx, gate.bottom - 7))
        self.label(screen, locked or "AIRLOCK OPEN", gate.x - 10, gate.y - 24, gate_color)
        if game.boss_hp:
            x, y = game.boss_position()
            x, y = round(x - camera.x), round(y - camera.y)
            sprite = game.art.boss[int(game.time * 11) % len(game.art.boss)]
            if sprite:
                screen.blit(sprite, sprite.get_rect(center=(x, y)))
            else:
                pg.draw.ellipse(screen, color, (x - 54, y - 34, 108, 68))
            for i in range(3):
                pg.draw.rect(screen, "#8fffea" if i < game.boss_hp else "#35364d",
                             (x - 31 + 22 * i, y - 54, 18, 5))
        for x, y, _, _ in game.pulses:
            pg.draw.circle(screen, "#78f4ff", (round(x - camera.x), round(y - camera.y)), 8, 2)
        for enemy in game.patrols:
            if enemy.active:
                enemy.draw(screen, game.art, camera, game.time)
        for x, y, _, _, life, tint in game.particles:
            size = max(2, round(life * 9))
            pg.draw.rect(screen, tint, (round(x - camera.x), round(y - camera.y), size, size))
        p = game.player
        if not game.equipped:
            self.portrait(screen, game.art.rider, round(p.x - camera.x), round(p.y - camera.y))
            self.portrait(screen, game.art.hand, round(211 - camera.x),
                          round(game.floor - camera.y))
            self.label(screen, "E  TAKE XPOGO", round(169 - camera.x), round(game.floor - 80 - camera.y),
                       "#ffbc77")
        else:
            if not game.immunity or int(game.time * 17) % 2 == 0:
                game.art.draw_rider(screen, p, camera)
            if game.charge:
                center = (round(p.x - camera.x), round(p.y - 28 - camera.y))
                pg.draw.circle(screen, "#fff1a5", center, round(22 + game.charge * 150), 3)
        if game.wave:
            x, y, radius = game.wave
            point = (round(x - camera.x), round(y - camera.y))
            pg.draw.circle(screen, "#fff2b0", point, round(radius), 6)
            pg.draw.circle(screen, "#ed83da", point, max(1, round(radius - 14)), 2)

    def draw(self, screen, game):
        screen.blit(self.sky, (0, 0))
        if game.state == "intro":
            self.intro(screen, game)
            return
        if game.state == "blackout":
            intensity = max(0, int(240 * (1 - game.state_time * 4)))
            screen.fill((intensity, intensity, intensity))
            return
        time = game.time
        shake = pg.Vector2(math.sin(time * 151), math.sin(time * 191)) * game.shake
        self.draw_world(screen, game, game.camera + shake)
        if game.flash:
            self.dim(screen, (255, 203, 151, int(330 * game.flash)))
        pg.draw.rect(screen, "#121827", (0, 0, WIDTH, 67))
        pg.draw.line(screen, game.level.color, (0, 66), (WIDTH, 66), 1)
        self.label(screen, f"0{game.number + 1} / 05   {game.level.name.upper()}", 23, 15,
                   game.level.color)
        ascent = max(0, game.floor - round(game.player.y))
        self.label(screen, f"ASCENT {ascent // 10:03} m", 23, 39, "#9caec6")
        screen.blit(game.art.healthbar, (371, 5))
        health = game.player.hp
        pg.draw.rect(screen, "#f64363" if health > LOW else "#bf77ff", (398, 23, round(174 * health / 100), 7))
        self.label(screen, f"{health:3}%   " + ("SHOCKWAVE READY" if health == FULL else "LIGHTER SPRING"),
                   385, 45, "#ffb5c8")
        self.label(screen, "A/D  Tilt    SHIFT  Brake", 696, 15, "#c4d0e7")
        self.label(screen, "E Interact  SPACE Attack  R Retry", 654, 39, "#c4d0e7")
        if game.message_time and game.state == "play":
            label = self.small.render(game.message, True, "#ebf2ff")
            rect = label.get_rect(midbottom=(WIDTH // 2, HEIGHT - 24))
            self.panel(screen, rect.inflate(28, 16), "#526582")
            screen.blit(label, rect)
        if game.state in ("briefing", "clear", "ending"):
            self.dim(screen, (5, 8, 18, 178))
            self.panel(screen, (180, 150, 600, 232), game.level.color)
            if game.state == "briefing":
                title, body, action = game.level.name, BRIEFINGS[game.number], "ENTER  Begin"
            elif game.state == "clear":
                title, body, action = "Airlock cleared", "Slimy presses on.", "ENTER  Continue"
            else:
                title = "PROTOPLASM"
                body = f"Slimy made it out. The Xpogo is going home. Checkpoint retries: {game.deaths}."
                action = "ENTER  Play again"
            self.label(screen, title, 216, 184, game.level.color, self.title)
            self.wrap(screen, body, 220, 254, 516)
            self.label(screen, action, 220, 340)


async def run_game():
    pg.init()
    browser = sys.platform == "emscripten"
    screen = pg.display.set_mode((WIDTH, HEIGHT))
    pg.display.set_caption("Protoplasm")
    game, view = Game(Art()), View()
    clock = pg.time.Clock()
    elapsed = 0.0
    while True:
        elapsed += min(clock.tick(0 if browser else 60) / 1000, 0.1)
        for event in pg.event.get():
            if event.type == pg.QUIT or (
                not browser and event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE
            ):
                pg.quit()
                return
            if event.type != pg.KEYDOWN:
                continue
            if event.key == pg.K_RETURN:
                if game.state == "intro" and game.state_time * 56 < len(INTRO[game.line][1]):
                    game.state_time = len(INTRO[game.line][1]) / 56 + 0.01
                else:
                    game.advance()
            elif event.key == pg.K_TAB and game.state == "intro":
                game.line = len(INTRO) - 1
                game.advance()
            elif event.key == pg.K_e:
                game.interact()
            elif event.key == pg.K_SPACE:
                game.attack()
            elif event.key == pg.K_r:
                game.respawn()
        keys = pg.key.get_pressed()
        direction = int(keys[pg.K_d] or keys[pg.K_RIGHT]) - int(keys[pg.K_a] or keys[pg.K_LEFT])
        while elapsed >= STEP:
            game.step(direction, STEP, keys[pg.K_LSHIFT] or keys[pg.K_RSHIFT])
            elapsed -= STEP
        view.draw(screen, game)
        pg.display.flip()
        await asyncio.sleep(0)


def main():
    asyncio.run(run_game())


if __name__ == "__main__":
    main()
