import pygame
import os
import time
import random
import sys
import signal
import csv
import datetime
import collections # Added for deque

# Attempt to import Raspberry Pi specific ADC modules
try:
    import board
    import busio
    import digitalio
    import adafruit_mcp3xxx.mcp3008 as MCP
    from adafruit_mcp3xxx.analog_in import AnalogIn
    RASPI_HW_AVAILABLE = True
except ImportError:
    RASPI_HW_AVAILABLE = False
except RuntimeError: # Catches issues like "no SPI device" if kernel modules aren't enabled
    RASPI_HW_AVAILABLE = False

# --- Constants and Parameters ---
FPS = 60
ADC_CHANNEL_NUMBER = 0
MIN_ADC_VALUE = 15823
MAX_ADC_VALUE = 65535

MIXER_FREQUENCY = 44100
MIXER_SIZE = -16
MIXER_CHANNELS_STEREO = 2
MIXER_BUFFER = 512
NUM_PYGAME_MIXER_CHANNELS = 16

THROTTLE_DEADZONE_LOW = 0.05
SUSTAINED_100_THROTTLE_TIME = 1.5
GESTURE_WINDOW_TIME = 0.75
GESTURE_MAX_POINTS = 20
FADE_OUT_MS = 300
CROSSFADE_DURATION_MS = 500
IDLE_TRANSITION_SPEED = 2.5
TURBO_BOV_COOLDOWN = 1.0
HIGH_REV_LIMITER_COOLDOWN = 1.5
FULL_ACCEL_RESET_IDLE_TIME = 3.0
NORMAL_IDLE_VOLUME = 0.7
LOW_IDLE_VOLUME_DURING_SFX = 0.15
VERY_LOW_IDLE_VOLUME_DURING_LAUNCH = 0.05
MASTER_ENGINE_VOL = 0.05 # Overall engine sound volume
LIGHT_BLIP_VOLUME = 0.9 # Specific volume for light blips relative to master

LAUNCH_CONTROL_THROTTLE_MIN = 0.55
LAUNCH_CONTROL_THROTTLE_MAX = 0.85
LAUNCH_CONTROL_HOLD_DURATION = 0.5
LAUNCH_CONTROL_BRAKE_REQUIRED = False # Set to True if brake input is needed
LAUNCH_CONTROL_ENGAGE_VOL = 1.0
LAUNCH_CONTROL_HOLD_VOL = 1.0

SOUND_FILES_PATH = "sounds"

CH_IDLE = 0
CH_TURBO_LIMITER_SFX = 1
CH_LONG_SEQUENCE_A = 2
CH_LONG_SEQUENCE_B = 3
CH_LIGHT_BLIP_START = 4
NUM_LIGHT_BLIP_CHANNELS = 3 # Number of channels dedicated to light blips

adc_throttle_channel = None # Placeholder for ADC channel object

# Logging and Display
DISPLAY_UPDATE_INTERVAL = 0.1 # seconds
LOG_FILE_NAME = "ev_sound_log.csv"
LIGHT_BLIP_GESTURE_COOLDOWN = 0.25 # Minimum time between playing light blip sounds
GESTURE_RETRIGGER_LOCKOUT = 0.3 # Seconds to wait after any gesture before initiating a new one

# --- Moving Average Parameters ---
THROTTLE_SMOOTHING_WINDOW_SIZE = 5 # Number of samples to average for throttle. Adjust as needed.

log_data = [] # Holds data for CSV logging

def initialize_adc():
    global adc_throttle_channel
    if not RASPI_HW_AVAILABLE:
        print("ADC hardware modules not available. Cannot initialize ADC.")
        return False
    try:
        # Create SPI bus
        spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)
        # Create chip select (CS) digital output
        cs = digitalio.DigitalInOut(board.D8) # Using D8 as CS, change if needed
        # Create MCP3008 object
        mcp = MCP.MCP3008(spi, cs)
        # Create analog input channel on the specified pin
        adc_throttle_channel = AnalogIn(mcp, getattr(MCP, f"P{ADC_CHANNEL_NUMBER}"))
        print(f"MCP3008 ADC initialized on channel P{ADC_CHANNEL_NUMBER}.")
        return True
    except Exception as e:
        print(f"FATAL ERROR initializing ADC: {e}")
        adc_throttle_channel = None
        return False

def read_adc_value():
    global adc_throttle_channel
    if adc_throttle_channel:
        try:
            return adc_throttle_channel.value
        except Exception as e:
            # print(f"Warning: Could not read ADC value: {e}") # Potentially spammy
            return MIN_ADC_VALUE # Return min value on error to simulate 0 throttle
    else:
        # Simulate 0% throttle if ADC is not available or failed
        return MIN_ADC_VALUE

def get_throttle_percentage_from_adc(raw_adc_value):
    if MAX_ADC_VALUE == MIN_ADC_VALUE: return 0.0 # Avoid division by zero
    # Clamp value to defined min/max range
    clamped_value = max(MIN_ADC_VALUE, min(raw_adc_value, MAX_ADC_VALUE))
    # Calculate percentage
    percentage = (clamped_value - MIN_ADC_VALUE) / (MAX_ADC_VALUE - MIN_ADC_VALUE)
    return percentage

class SoundManager:
    def __init__(self):
        self.sounds = {}
        self.load_sounds()
        self.channel_idle = pygame.mixer.Channel(CH_IDLE)
        self.channel_turbo_limiter_sfx = pygame.mixer.Channel(CH_TURBO_LIMITER_SFX)
        self.idle_target_volume = NORMAL_IDLE_VOLUME
        self.idle_current_volume = NORMAL_IDLE_VOLUME
        self.idle_is_fading = False

        self.light_blip_channels = []
        if pygame.mixer.get_init() and pygame.mixer.get_num_channels() >= CH_LIGHT_BLIP_START + NUM_LIGHT_BLIP_CHANNELS:
            for i in range(NUM_LIGHT_BLIP_CHANNELS):
                self.light_blip_channels.append(pygame.mixer.Channel(CH_LIGHT_BLIP_START + i))
            print(f"Initialized {NUM_LIGHT_BLIP_CHANNELS} dedicated light blip channels starting from {CH_LIGHT_BLIP_START}.")
        else:
            mixer_channels = pygame.mixer.get_num_channels() if pygame.mixer.get_init() else 'Mixer not init'
            needed_channels = CH_LIGHT_BLIP_START + NUM_LIGHT_BLIP_CHANNELS
            print(f"Warning: Not enough mixer channels ({mixer_channels}) to dedicate for light blips. Need {needed_channels}.")


        self.waiting_for_launch_hold_loop = False
        self.launch_control_sounds_active = False # Tracks if LC sounds (engage or hold) are playing
        self.channel_long_A = pygame.mixer.Channel(CH_LONG_SEQUENCE_A)
        self.channel_long_B = pygame.mixer.Channel(CH_LONG_SEQUENCE_B)
        self.active_long_channel = self.channel_long_A # Start with A
        self.transitioning_long_sound = False
        self.transition_start_time = 0

    def load_sounds(self):
        self.sounds['idle'] = self._load_sound("engine_idle_loop.wav")
        self.sounds['light_blip'] = [
            self._load_sound("engine_light_blip_01.wav"),
            self._load_sound("engine_light_blip_02.wav"),
            self._load_sound("engine_light_blip_03.wav")
        ]
        self.sounds['turbo_bov'] = self._load_sound("turbo_spool_and_bov.wav")
        self.sounds['rev_limiter'] = self._load_sound("engine_high_rev_with_limiter.wav")
        self.sounds['accel_gears'] = self._load_sound("acceleration_gears_1_to_4.wav")
        self.sounds['cruising'] = self._load_sound("engine_cruising_loop.wav")
        self.sounds['decel_downshifts'] = self._load_sound("deceleration_downshifts_to_idle.wav")
        self.sounds['starter'] = self._load_sound("engine_starter.wav")
        self.sounds['launch_control_engage'] = self._load_sound("launch_control_engage.wav")
        self.sounds['launch_control_hold_loop'] = self._load_sound("launch_control_hold_loop.wav")

    def _load_sound(self, filename):
        path = os.path.join(SOUND_FILES_PATH, filename)
        if os.path.exists(path):
            try: return pygame.mixer.Sound(path)
            except pygame.error as e: print(f"Warning: Could not load '{filename}': {e}"); return None
        print(f"Warning: Sound file not found '{filename}' at '{path}'"); return None

    def get_sound_name_from_obj(self, sound_obj):
        if sound_obj is None: return "None"
        for name, sound_asset in self.sounds.items():
            if isinstance(sound_asset, list): # If the sound is part of a list (like light_blips)
                for i, s_item in enumerate(sound_asset):
                    if s_item == sound_obj: return f"{name}[{i}]"
            elif sound_asset == sound_obj: return name
        return "UnknownSoundObject"

    def update(self):
        # Logic for transitioning from launch_control_engage to launch_control_hold_loop
        lc_engage_sound = self.sounds.get('launch_control_engage')
        lc_hold_sound = self.sounds.get('launch_control_hold_loop')
        current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()

        if self.waiting_for_launch_hold_loop:
            # If the engage sound has finished playing
            if not self.channel_turbo_limiter_sfx.get_busy() or current_sfx_sound != lc_engage_sound:
                if lc_hold_sound:
                    self.channel_turbo_limiter_sfx.set_volume(LAUNCH_CONTROL_HOLD_VOL * MASTER_ENGINE_VOL)
                    self.channel_turbo_limiter_sfx.play(lc_hold_sound, loops=-1)
                    # self.launch_control_sounds_active remains true
                else: # No hold sound, so LC sequence effectively ends
                    self.launch_control_sounds_active = False
                self.waiting_for_launch_hold_loop = False
        
        # Update overall launch_control_sounds_active state
        # This flag indicates if *any* part of the LC sound sequence is currently meant to be active.
        # It's primarily set by play_launch_control_sequence and stop_launch_control_sequence.
        # Here, we ensure it's false if sounds unexpectedly stop or are not LC sounds.
        if self.launch_control_sounds_active: # Only if we think it *should* be active
            if not self.waiting_for_launch_hold_loop and \
               (not self.channel_turbo_limiter_sfx.get_busy() or \
                (current_sfx_sound != lc_engage_sound and current_sfx_sound != lc_hold_sound)):
                # If we are not waiting for hold loop, and the SFX channel is free,
                # or is playing something other than LC sounds, then LC is no longer active.
                self.launch_control_sounds_active = False


    def play_idle(self):
        idle_sound = self.sounds.get('idle')
        if idle_sound:
            if not self.channel_idle.get_busy() or self.channel_idle.get_sound() != idle_sound:
                self.channel_idle.play(idle_sound, loops=-1)
            # Set volume immediately based on current target, fade will adjust if needed
            self.idle_current_volume = self.idle_target_volume # Sync current with target on play
            self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
            self.idle_is_fading = abs(self.idle_current_volume - self.idle_target_volume) > 0.01


    def set_idle_target_volume(self, target_volume, instant=False):
        target_volume = max(0.0, min(1.0, target_volume)) # Clamp volume
        if abs(self.idle_target_volume - target_volume) > 0.01 or instant : # If target changed significantly or instant flag
            self.idle_target_volume = target_volume
            if instant:
                self.idle_current_volume = target_volume
                if self.channel_idle.get_sound(): # Check if sound object exists
                     self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
                self.idle_is_fading = False
            else: # If not instant, enable fading if current volume is different from new target
                if abs(self.idle_current_volume - self.idle_target_volume) > 0.01:
                    self.idle_is_fading = True

    def update_idle_fade(self, dt):
        if self.idle_is_fading and self.channel_idle.get_busy():
            if abs(self.idle_current_volume - self.idle_target_volume) < 0.01: # Close enough
                self.idle_current_volume = self.idle_target_volume
                self.idle_is_fading = False
            elif self.idle_current_volume < self.idle_target_volume:
                self.idle_current_volume = min(self.idle_current_volume + IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            else: # self.idle_current_volume > self.idle_target_volume
                self.idle_current_volume = max(self.idle_current_volume - IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            
            if self.channel_idle.get_sound(): # Check if sound object exists
                self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)

    def stop_idle(self):
        self.channel_idle.stop()
        self.idle_is_fading = False # Stop any fading process

    def play_light_blip(self):
        if not self.light_blip_channels: return False # No dedicated channels
        valid_blips = [s for s in self.sounds.get('light_blip', []) if s is not None]
        if not valid_blips: return False # No valid blip sounds loaded
        
        sound_to_play = random.choice(valid_blips)
        for blip_channel in self.light_blip_channels:
            if not blip_channel.get_busy():
                blip_channel.set_volume(LIGHT_BLIP_VOLUME * MASTER_ENGINE_VOL)
                blip_channel.play(sound_to_play)
                return True # Sound played
        return False # All blip channels busy

    def play_turbo_or_limiter_sfx(self, sound_key):
        sound_to_play = self.sounds.get(sound_key)
        if sound_to_play:
            # If launch control is active, stop it before playing other SFX
            if self.is_launch_control_active():
                self.stop_launch_control_sequence(fade_ms=100) # Quick fade for LC if it's on
            
            self.channel_turbo_limiter_sfx.set_volume(MASTER_ENGINE_VOL) # Use master for these
            self.channel_turbo_limiter_sfx.play(sound_to_play)
            return True
        return False

    def play_starter_sfx(self):
        sound_to_play = self.sounds.get('starter')
        if sound_to_play:
            # Ensure it doesn't interrupt an ongoing launch control sequence
            current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
            lc_engage = self.sounds.get('launch_control_engage')
            lc_hold = self.sounds.get('launch_control_hold_loop')

            if not self.channel_turbo_limiter_sfx.get_busy() or \
               (current_sfx_sound != lc_engage and current_sfx_sound != lc_hold):
                self.channel_turbo_limiter_sfx.stop() # Stop whatever non-LC sound might be playing
                self.channel_turbo_limiter_sfx.set_volume(MASTER_ENGINE_VOL)
                self.channel_turbo_limiter_sfx.play(sound_to_play)
                return True
        return False

    def stop_turbo_limiter_sfx(self):
        # This should not stop launch control sounds, only other SFX on this channel
        current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
        lc_engage = self.sounds.get('launch_control_engage')
        lc_hold = self.sounds.get('launch_control_hold_loop')

        if current_sfx_sound != lc_engage and current_sfx_sound != lc_hold:
            self.channel_turbo_limiter_sfx.stop()

    def is_turbo_limiter_sfx_busy(self):
        # Is the channel busy with something OTHER than launch control sounds?
        if self.channel_turbo_limiter_sfx.get_busy():
            current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
            lc_engage = self.sounds.get('launch_control_engage')
            lc_hold = self.sounds.get('launch_control_hold_loop')
            if current_sfx_sound != lc_engage and current_sfx_sound != lc_hold:
                return True
        return False

    def any_playful_sfx_active(self):
        # Check light blip channels
        for blip_channel in self.light_blip_channels:
            if blip_channel.get_busy(): return True
        
        # Check main SFX channel for non-LC sounds
        if self.channel_turbo_limiter_sfx.get_busy():
            current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
            lc_engage = self.sounds.get('launch_control_engage')
            lc_hold = self.sounds.get('launch_control_hold_loop')
            # If it's busy and NOT a launch control sound, then a playful SFX is active
            if current_sfx_sound != lc_engage and current_sfx_sound != lc_hold:
                return True
        return False

    def stop_all_light_blips(self):
        for blip_channel in self.light_blip_channels: blip_channel.stop()

    def get_active_blip_count(self):
        return sum(1 for ch in self.light_blip_channels if ch.get_busy())


    def play_launch_control_sequence(self):
        engage_sound = self.sounds.get('launch_control_engage')
        hold_sound = self.sounds.get('launch_control_hold_loop')

        if engage_sound:
            self.channel_turbo_limiter_sfx.stop() # Stop anything else on this channel
            self.channel_turbo_limiter_sfx.set_volume(LAUNCH_CONTROL_ENGAGE_VOL * MASTER_ENGINE_VOL)
            self.channel_turbo_limiter_sfx.play(engage_sound)
            self.waiting_for_launch_hold_loop = True
            self.launch_control_sounds_active = True # LC is now active
            return True
        elif hold_sound: # Fallback if engage sound is missing
            print("Launch control engage sound missing, playing hold loop directly.")
            self.channel_turbo_limiter_sfx.stop()
            self.channel_turbo_limiter_sfx.set_volume(LAUNCH_CONTROL_HOLD_VOL * MASTER_ENGINE_VOL)
            self.channel_turbo_limiter_sfx.play(hold_sound, loops=-1)
            self.waiting_for_launch_hold_loop = False # No waiting needed
            self.launch_control_sounds_active = True # LC is now active
            return True
        
        # If neither sound is available
        self.launch_control_sounds_active = False 
        return False

    def stop_launch_control_sequence(self, fade_ms=FADE_OUT_MS // 2):
        current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
        lc_engage = self.sounds.get('launch_control_engage')
        lc_hold = self.sounds.get('launch_control_hold_loop')

        # Only stop if a launch control sound is actually playing
        if self.channel_turbo_limiter_sfx.get_busy() and \
           (current_sfx_sound == lc_engage or current_sfx_sound == lc_hold):
            if fade_ms > 0: self.channel_turbo_limiter_sfx.fadeout(fade_ms)
            else: self.channel_turbo_limiter_sfx.stop()
        
        self.waiting_for_launch_hold_loop = False
        self.launch_control_sounds_active = False # LC is no longer active

    def is_launch_control_active(self):
        # Is any part of the launch control sequence (engage, waiting for hold, or hold) active?
        return self.launch_control_sounds_active or self.waiting_for_launch_hold_loop
    
    def play_long_sequence(self, sound_key, loops=0, transition_from_other=False):
        sound_to_play = self.sounds.get(sound_key)
        if not sound_to_play:
            print(f"Long sequence sound key '{sound_key}' not found.")
            # Stop both long channels if the requested sound is missing
            other_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A
            other_channel.stop()
            self.active_long_channel.stop()
            self.transitioning_long_sound = False
            return

        if not transition_from_other:
            # Stop the other channel immediately
            other_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A
            other_channel.stop()
            # Play on the currently active channel
            self.active_long_channel.set_volume(MASTER_ENGINE_VOL)
            self.active_long_channel.play(sound_to_play, loops=loops)
            self.transitioning_long_sound = False
        else:
            # Crossfade: fade out current, fade in new on the other channel
            fade_out_channel = self.active_long_channel
            fade_in_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A

            fade_out_channel.fadeout(CROSSFADE_DURATION_MS)
            
            fade_in_channel.set_volume(0) # Start silent
            fade_in_channel.play(sound_to_play, loops=loops)
            
            self.active_long_channel = fade_in_channel # Switch active channel
            self.transitioning_long_sound = True
            self.transition_start_time = time.time()

    def update_long_sequence_crossfade(self):
        if self.transitioning_long_sound:
            elapsed_time_ms = (time.time() - self.transition_start_time) * 1000
            progress = min(1.0, elapsed_time_ms / CROSSFADE_DURATION_MS)
            
            if self.active_long_channel.get_busy(): # Check if the new channel is playing
                 self.active_long_channel.set_volume(progress * MASTER_ENGINE_VOL)

            if progress >= 1.0:
                self.transitioning_long_sound = False
                # Ensure final volume is set correctly if sound is still playing
                if self.active_long_channel.get_busy():
                    self.active_long_channel.set_volume(MASTER_ENGINE_VOL)

    def stop_long_sequence(self, fade_ms=0):
        if fade_ms > 0:
            self.channel_long_A.fadeout(fade_ms)
            self.channel_long_B.fadeout(fade_ms)
        else:
            self.channel_long_A.stop()
            self.channel_long_B.stop()
        self.transitioning_long_sound = False

    def is_long_sequence_busy(self):
        return self.channel_long_A.get_busy() or self.channel_long_B.get_busy() or self.transitioning_long_sound

class EngineSimulation:
    def __init__(self, sound_manager):
        self.sm = sound_manager
        self.state = "ENGINE_OFF" 
        self.current_throttle = 0.0 # This will now store the SMOOTHED throttle
        self.throttle_history = collections.deque(maxlen=GESTURE_MAX_POINTS) # Using deque for history   
        self.peak_throttle_in_gesture = 0.0
        self.gesture_start_time = 0.0
        self.in_potential_gesture = False
        
        self.last_turbo_bov_time = 0.0
        self.last_rev_limiter_time = 0.0
        self.last_light_blip_played_time = 0.0
        self.gesture_lockout_until_time = 0.0 # ADDED: Time until a new gesture can be initiated

        self.time_at_100_throttle = 0.0
        self.time_in_idle = 0.0
        self.played_full_accel_sequence_recently = False
        self.time_in_launch_control_range = 0.0


    def update(self, dt, new_throttle_value): # new_throttle_value is now the SMOOTHED throttle
        previous_throttle_this_frame = self.current_throttle
        self.current_throttle = new_throttle_value # Use the smoothed value directly
        current_time = time.time()

        # Throttle history for gesture detection should use the (now smoothed) current_throttle
        self.throttle_history.append((current_time, self.current_throttle))
        # self.throttle_history = self.throttle_history[-GESTURE_MAX_POINTS:] # Deque handles maxlen

        self.sm.update_long_sequence_crossfade()
        self.sm.update_idle_fade(dt)
        self.sm.update() # Call SoundManager's own update for LC transition

        # --- State Machine Logic (uses self.current_throttle which is smoothed) ---
        if self.state == "ENGINE_OFF":
            if self.current_throttle > THROTTLE_DEADZONE_LOW + 0.05: # Small margin to start
                print("\nEngine Starting Triggered...")
                self.state = "STARTING"
                self.sm.play_starter_sfx()
                # Optional: Reset throttle briefly to prevent immediate revving after start
                self.current_throttle = 0.0 
                self.throttle_history.append((current_time, self.current_throttle))


        elif self.state == "STARTING":
            # Transition to IDLING once starter sound finishes (and not in LC by mistake)
            if not self.sm.is_turbo_limiter_sfx_busy() and not self.sm.is_launch_control_active():
                print("\nEngine Idling.")
                self.state = "IDLING"
                self.sm.set_idle_target_volume(NORMAL_IDLE_VOLUME)
                self.sm.play_idle()
                self.time_in_idle = 0.0

        elif self.state == "IDLING" or self.state == "PLAYFUL_REV":
            if self.state == "IDLING":
                self.time_in_idle += dt
                if self.time_in_idle > FULL_ACCEL_RESET_IDLE_TIME:
                    self.played_full_accel_sequence_recently = False
                # If no playful sounds or LC active, set idle to normal
                if not self.sm.any_playful_sfx_active() and not self.sm.is_launch_control_active():
                     self.sm.set_idle_target_volume(NORMAL_IDLE_VOLUME)
            else: # PLAYFUL_REV state
                self.sm.set_idle_target_volume(LOW_IDLE_VOLUME_DURING_SFX)
                # If playful sounds finish, transition back to IDLING
                if not self.sm.any_playful_sfx_active():
                    self.state = "IDLING"
                    self.time_in_idle = 0.0 # Reset idle timer
                    self.sm.set_idle_target_volume(NORMAL_IDLE_VOLUME) # Start transition to normal idle vol

            is_in_lc_throttle_range = (LAUNCH_CONTROL_THROTTLE_MIN < self.current_throttle < LAUNCH_CONTROL_THROTTLE_MAX)
            
            # Launch Control Engagement Logic:
            # Only try to engage if not already in LAUNCH_HOLD state.
            if is_in_lc_throttle_range and (not LAUNCH_CONTROL_BRAKE_REQUIRED) and self.state != "LAUNCH_HOLD":
                self.time_in_launch_control_range += dt
                # Check if duration met AND LC is not already active/being initiated by SoundManager
                if self.time_in_launch_control_range >= LAUNCH_CONTROL_HOLD_DURATION and not self.sm.is_launch_control_active():
                    print("\nLaunch Control Engaged!")
                    self.state = "LAUNCH_HOLD"
                    self.sm.stop_all_light_blips()      # Stop blips
                    self.sm.stop_turbo_limiter_sfx()  # Stop other SFX (turbo/revlim)
                    if self.sm.play_launch_control_sequence():
                         self.sm.set_idle_target_volume(VERY_LOW_IDLE_VOLUME_DURING_LAUNCH, instant=True)
                    else: # Sound sequence failed to start
                        self.state = "IDLING" # Revert to idling
                    self.time_in_launch_control_range = 0.0 # Reset timer
                    self.time_at_100_throttle = 0.0 # Reset full throttle timer
                    return # Exit update for this frame as state change is significant
            # If throttle is out of LC range AND we are not in LAUNCH_HOLD state yet, reset timer.
            elif not is_in_lc_throttle_range and self.state != "LAUNCH_HOLD":
                self.time_in_launch_control_range = 0.0

            # Playful gestures check (only if not in launch hold)
            if self.state != "LAUNCH_HOLD": # Ensure we don't check for blips during LC
                self._check_playful_gestures(current_time, previous_throttle_this_frame)

            # Full acceleration check (from idle/playful, not from launch hold)
            if self.current_throttle >= 0.98: # Sustained near 100% throttle
                self.time_at_100_throttle += dt
                if self.time_at_100_throttle >= SUSTAINED_100_THROTTLE_TIME and \
                   not self.played_full_accel_sequence_recently and \
                   self.state not in ["ACCELERATING", "LAUNCH_HOLD"]: # Don't trigger if already accelerating or in LC
                    print("\nFull Acceleration!")
                    self.state = "ACCELERATING"
                    self.sm.set_idle_target_volume(0.0, instant=True) # Idle off
                    self.sm.stop_launch_control_sequence(fade_ms=50) # Ensure LC is fully off
                    self.sm.stop_turbo_limiter_sfx() # Stop any other SFX
                    self.sm.stop_all_light_blips()   # Stop blips
                    self.sm.play_long_sequence('accel_gears')
                    self.played_full_accel_sequence_recently = True
                    self.time_at_100_throttle = 0.0
            else: # Throttle not at 100%
                self.time_at_100_throttle = 0.0


        elif self.state == "LAUNCH_HOLD":
            self.sm.set_idle_target_volume(VERY_LOW_IDLE_VOLUME_DURING_LAUNCH, instant=True)
            if self.current_throttle >= 0.98: # Launching (full throttle from hold)
                print("\nLaunching!")
                self.state = "ACCELERATING"
                # Stop LC sounds immediately (no fade for abrupt launch)
                self.sm.stop_launch_control_sequence(fade_ms=0) 
                self.sm.set_idle_target_volume(0.0, instant=True) # Idle off
                self.sm.play_long_sequence('accel_gears')
                self.played_full_accel_sequence_recently = True # Count this as a full accel
            # Check for disengagement (throttle out of range OR sound manager reports LC no longer active)
            elif not (LAUNCH_CONTROL_THROTTLE_MIN < self.current_throttle < LAUNCH_CONTROL_THROTTLE_MAX) or \
                 not self.sm.is_launch_control_active(): # If SM says LC sounds stopped for any reason
                if self.sm.is_launch_control_active(): # Only print if SM thought it was active
                    print("\nLaunch Control Disengaged.")
                self.state = "IDLING"
                self.sm.stop_launch_control_sequence() # Ensure sounds are stopped
                self.sm.set_idle_target_volume(NORMAL_IDLE_VOLUME)
                if self.sm.sounds.get('idle'): self.sm.play_idle() # Re-start idle if not playing
                self.time_in_idle = 0.0


        elif self.state == "ACCELERATING":
            self.sm.set_idle_target_volume(0.0, instant=True) # Keep idle off
            if self.current_throttle < 0.90: # If throttle drops significantly
                if self.state != "DECELERATING": print("\nDecelerating...")
                self.state = "DECELERATING"
                self.sm.play_long_sequence('decel_downshifts', transition_from_other=True)
            # If accel sound finishes but throttle still high -> cruising
            elif not self.sm.is_long_sequence_busy() and not self.sm.transitioning_long_sound:
                if self.current_throttle >= 0.90: # Still high throttle
                    if self.state != "CRUISING": print("\nCruising...")
                    self.state = "CRUISING"
                    self.sm.play_long_sequence('cruising', loops=-1, transition_from_other=True)
                else: # Throttle dropped as sound ended
                    if self.state != "DECELERATING": print("\nDecelerating (from accel end)...")
                    self.state = "DECELERATING"
                    self.sm.play_long_sequence('decel_downshifts', transition_from_other=True)

        elif self.state == "CRUISING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            if self.current_throttle < 0.90: # Throttle drops below cruising threshold
                if self.state != "DECELERATING": print("\nDecelerating (from cruise)...")
                self.state = "DECELERATING"
                self.sm.play_long_sequence('decel_downshifts', transition_from_other=True)

        elif self.state == "DECELERATING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            # If throttle goes back up during decel (and not mid-transition) -> cruising
            if self.current_throttle >= 0.95 and not self.sm.transitioning_long_sound:
                if self.state != "CRUISING": print("\nBack to Cruising (from decel)...")
                self.state = "CRUISING"
                self.sm.play_long_sequence('cruising', loops=-1, transition_from_other=True)
                self.played_full_accel_sequence_recently = True # Re-accelerating means accel sequence effectively used
            # If decel sound finishes -> idling
            elif not self.sm.is_long_sequence_busy() and not self.sm.transitioning_long_sound:
                if self.state != "IDLING": print("\nBack to Idling (from decel end).")
                self.state = "IDLING"
                self.sm.set_idle_target_volume(NORMAL_IDLE_VOLUME)
                if self.sm.sounds.get('idle'): self.sm.play_idle()
                self.time_in_idle = 0.0

    def _check_playful_gestures(self, current_time, old_throttle_value_for_frame):
        if self.sm.is_long_sequence_busy() or self.state == "LAUNCH_HOLD" or self.sm.is_launch_control_active():
            self.in_potential_gesture = False # Cannot do playful gestures during these
            return

        # Try to start a new gesture ONLY if not in lockout and conditions met
        if not self.in_potential_gesture and current_time >= self.gesture_lockout_until_time:
            # Condition to start a gesture: throttle rises from deadzone
            is_rising_from_idle = (len(self.throttle_history) < 2 or self.throttle_history[-2][1] <= THROTTLE_DEADZONE_LOW)
            if self.current_throttle > THROTTLE_DEADZONE_LOW and is_rising_from_idle:
                self.in_potential_gesture = True
                self.gesture_start_time = current_time
                self.peak_throttle_in_gesture = self.current_throttle
        
        if self.in_potential_gesture:
            self.peak_throttle_in_gesture = max(self.peak_throttle_in_gesture, self.current_throttle)

            # Gesture timed out or window passed
            if current_time - self.gesture_start_time > GESTURE_WINDOW_TIME:
                self.in_potential_gesture = False
                return

            # Condition for gesture to be recognized: throttle falling after a peak, back to near idle
            is_falling_after_peak = (self.current_throttle < self.peak_throttle_in_gesture * 0.7) and \
                                    (self.current_throttle < old_throttle_value_for_frame) and \
                                    (self.current_throttle <= THROTTLE_DEADZONE_LOW * 1.5) # Must fall back to near deadzone

            if is_falling_after_peak and self.peak_throttle_in_gesture > THROTTLE_DEADZONE_LOW + 0.02: # Min peak to be considered a gesture
                current_peak = self.peak_throttle_in_gesture
                
                # This gesture has concluded. End it and set lockout.
                self.in_potential_gesture = False 
                self.gesture_lockout_until_time = current_time + GESTURE_RETRIGGER_LOCKOUT

                triggered_any_sfx = False

                # Determine type of gesture based on the peak throttle achieved
                if current_peak <= 0.40: # Light throttle blip
                    if current_time - self.last_light_blip_played_time > LIGHT_BLIP_GESTURE_COOLDOWN:
                        if self.sm.play_light_blip():
                            self.last_light_blip_played_time = current_time
                            triggered_any_sfx = True
                # Check for turbo/limiter only if not busy with other sfx (unless it's launch control, handled by play_turbo_or_limiter_sfx)
                elif not self.sm.is_turbo_limiter_sfx_busy() or not self.sm.is_launch_control_active(): # Check is_launch_control_active here too
                    if self.sm.is_launch_control_active(): # Defensive: if somehow LC is active, stop it
                        self.sm.stop_launch_control_sequence(fade_ms=50)

                    # MODIFIED: Turbo threshold starts at 0.45
                    if 0.45 < current_peak <= 0.70: # Turbo spool/BOV
                        if current_time - self.last_turbo_bov_time > TURBO_BOV_COOLDOWN:
                            if self.sm.play_turbo_or_limiter_sfx('turbo_bov'):
                                self.last_turbo_bov_time = current_time
                                triggered_any_sfx = True
                    elif current_peak > 0.70: # Rev limiter
                        if current_time - self.last_rev_limiter_time > HIGH_REV_LIMITER_COOLDOWN:
                            if self.sm.play_turbo_or_limiter_sfx('rev_limiter'):
                                self.last_rev_limiter_time = current_time
                                triggered_any_sfx = True
                                
                if triggered_any_sfx:
                    self.sm.set_idle_target_volume(LOW_IDLE_VOLUME_DURING_SFX)
                    if self.state in ["IDLING", "PLAYFUL_REV"]: # Can transition from IDLING or stay in PLAYFUL_REV
                        self.state = "PLAYFUL_REV"
                    self.time_at_100_throttle = 0.0 # Reset full throttle timer if a blip occurs


running_script = True # Global flag to control main loop
def signal_handler_main(sig, frame):
    global running_script
    if running_script: # Prevent multiple calls if signal is received again
        print("\nInterrupt received. Shutting down...")
        running_script = False

def update_display(sim_state, current_throttle_smoothed, raw_throttle_pct, raw_adc, lc_time, idle_vol, lc_active_sm, num_blips):
    status_string = (
        f"State: {sim_state:<15} | RawThr: {raw_throttle_pct:>4.2f} | SmoothThr: {current_throttle_smoothed:>4.2f} | "
        f"ADC: {raw_adc:<5} | "
        f"LC_T: {lc_time if sim_state != 'LAUNCH_HOLD' else LAUNCH_CONTROL_HOLD_DURATION:>4.2f}s | IdleVol: {idle_vol:>4.2f} | "
        f"LC_SFX: {str(lc_active_sm):<5} | Blips: {num_blips:<1}"
    )
    print(f"\r{status_string:<145}", end='', flush=True) # Ensure enough padding to overwrite previous line

def main():
    global running_script, adc_throttle_channel, log_data
    # Setup signal handlers for graceful exit
    signal.signal(signal.SIGINT, signal_handler_main)
    signal.signal(signal.SIGTERM, signal_handler_main)

    pygame.init() # Initialize all Pygame modules
    
    actual_channels = 0
    min_channels_needed = CH_LIGHT_BLIP_START + NUM_LIGHT_BLIP_CHANNELS
    mixer_initialized_ok = False

    # Attempt to initialize mixer with preferred settings
    try:
        pygame.mixer.init(frequency=MIXER_FREQUENCY, size=MIXER_SIZE, channels=MIXER_CHANNELS_STEREO, buffer=MIXER_BUFFER)
        if pygame.mixer.get_init(): # Check if initialization was successful
            pygame.mixer.set_num_channels(NUM_PYGAME_MIXER_CHANNELS)
            actual_channels = pygame.mixer.get_num_channels()
            print(f"Pygame Mixer initialized. Requested {NUM_PYGAME_MIXER_CHANNELS}, Got {actual_channels} channels.")
            mixer_initialized_ok = True
        else:
            print("Pygame Mixer failed to initialize with custom settings.")
    except pygame.error as e:
        print(f"Error initializing Pygame mixer with custom settings: {e}.")

    # Fallback to default mixer settings if custom failed
    if not mixer_initialized_ok:
        print("Attempting Pygame Mixer default initialization...")
        try:
            pygame.mixer.init() # Default settings
            if pygame.mixer.get_init():
                pygame.mixer.set_num_channels(NUM_PYGAME_MIXER_CHANNELS) # Still try to set num channels
                actual_channels = pygame.mixer.get_num_channels()
                print(f"Pygame Mixer fallback initialization succeeded. Requested {NUM_PYGAME_MIXER_CHANNELS}, Got {actual_channels} channels.")
                mixer_initialized_ok = True
            else:
                print("CRITICAL ERROR: Pygame Mixer failed to initialize even with default settings.")
                actual_channels = 0 # Ensure it's zero if failed
        except pygame.error as e_fallback:
            print(f"CRITICAL ERROR: Pygame Mixer fallback initialization also failed: {e_fallback}.")
            actual_channels = 0

    if mixer_initialized_ok and actual_channels < min_channels_needed:
        print(f"CRITICAL WARNING: Mixer has {actual_channels} channels, but {min_channels_needed} are needed for all features (e.g., light blips). Sound issues may occur.")
    elif not mixer_initialized_ok:
         print("Mixer initialization ultimately failed. SoundManager might not be able to create sound channels correctly.")


    # Initialize ADC if Raspberry Pi hardware is detected
    if not RASPI_HW_AVAILABLE:
        print("--- RUNNING IN SIMULATED ADC MODE (NO RASPBERRY PI HARDWARE DETECTED/INITIALIZED) ---")
    else:
        if not initialize_adc():
            # If ADC init fails, run in simulated mode with 0% throttle
            print("--- FAILED TO INITIALIZE ADC. SIMULATING 0% THROTTLE (MIN_ADC_VALUE) ---")
        else:
            print("--- RUNNING WITH RASPBERRY PI ADC HARDWARE ---")

    # Ensure sound directory exists
    os.makedirs(SOUND_FILES_PATH, exist_ok=True)
    # Check for critical sound files
    sound_files_to_check = [
        "engine_idle_loop.wav", "engine_light_blip_01.wav", # ... add more as needed
        "launch_control_engage.wav", "launch_control_hold_loop.wav", "acceleration_gears_1_to_4.wav"
    ]
    missing_files = any(not os.path.exists(os.path.join(SOUND_FILES_PATH, sf)) for sf in sound_files_to_check)
    if missing_files:
        for sf in sound_files_to_check:
            if not os.path.exists(os.path.join(SOUND_FILES_PATH, sf)):
                print(f"Warning: Essential sound file '{sf}' not found in '{SOUND_FILES_PATH}/'. Please add it.")
        print("--- Some essential sound files are missing. Functionality will be significantly affected. ---")


    sound_manager_instance = SoundManager() 
    simulation = EngineSimulation(sound_manager_instance)
    
    # Initialize deque for throttle smoothing
    throttle_buffer = collections.deque(maxlen=THROTTLE_SMOOTHING_WINDOW_SIZE)
    # Pre-fill buffer with initial zero throttle to avoid skewed average at start
    for _ in range(THROTTLE_SMOOTHING_WINDOW_SIZE):
        throttle_buffer.append(0.0)

    print("\nEV Sound Simulation Running (Headless)...")
    print(f"Throttle smoothing window: {THROTTLE_SMOOTHING_WINDOW_SIZE} samples")
    print(f"Gesture peak thresholds: Light Blip <= 40%, Turbo 45-70%, Rev Limiter > 70%") # Updated Turbo threshold
    print(f"Gesture Retrigger Lockout: {GESTURE_RETRIGGER_LOCKOUT}s")
    print(f"Blip Cooldown: {LIGHT_BLIP_GESTURE_COOLDOWN}s")
    print(f"Throttle Input: ADC P{ADC_CHANNEL_NUMBER} -> {MIN_ADC_VALUE} (0%) to {MAX_ADC_VALUE} (100%)")
    print(f"Launch Control: Hold throttle {LAUNCH_CONTROL_THROTTLE_MIN*100:.0f}%-"
          f"{LAUNCH_CONTROL_THROTTLE_MAX*100:.0f}% for {LAUNCH_CONTROL_HOLD_DURATION}s")
    print(f"Log file will be: {LOG_FILE_NAME}")
    print("Press Ctrl+C to exit gracefully.\n")


    last_time = time.time()
    last_display_update_time = time.time()

    try:
        while running_script:
            current_time_loop = time.time()
            dt = current_time_loop - last_time
            if dt <= 0: dt = 1/FPS # Ensure dt is positive and non-zero
            last_time = current_time_loop

            raw_adc = read_adc_value()
            raw_throttle_percentage = get_throttle_percentage_from_adc(raw_adc)
            
            # Apply moving average
            throttle_buffer.append(raw_throttle_percentage)
            smoothed_throttle_percentage = sum(throttle_buffer) / len(throttle_buffer)
            
            simulation.update(dt, smoothed_throttle_percentage) # Pass smoothed value to simulation
            # sound_manager_instance.update() # Already called within simulation.update() for LC transition

            # Log data (consider moving to a less frequent interval if performance is an issue)
            log_entry = {
                "timestamp_unix": current_time_loop,
                "datetime_iso": datetime.datetime.now().isoformat(),
                "dt": dt,
                "state": simulation.state,
                "raw_adc": raw_adc,
                "raw_throttle_input_pct": raw_throttle_percentage,
                "smoothed_throttle_pct": smoothed_throttle_percentage,
                "sim_current_throttle_pct": simulation.current_throttle, # This is the smoothed value used by sim
                "idle_target_vol": sound_manager_instance.idle_target_volume,
                "idle_current_vol": sound_manager_instance.idle_current_volume,
                "idle_is_fading": sound_manager_instance.idle_is_fading,
                "idle_chan_busy": sound_manager_instance.channel_idle.get_busy(),
                "active_blip_count": sound_manager_instance.get_active_blip_count(),
                "sfx_chan_busy": sound_manager_instance.channel_turbo_limiter_sfx.get_busy(), # Overall busy state
                "sfx_chan_sound": sound_manager_instance.get_sound_name_from_obj(sound_manager_instance.channel_turbo_limiter_sfx.get_sound()),
                "sm_lc_sounds_active": sound_manager_instance.launch_control_sounds_active, # SoundManager's view of LC
                "sm_waiting_for_lc_hold": sound_manager_instance.waiting_for_launch_hold_loop,
                "sm_is_lc_active_overall": sound_manager_instance.is_launch_control_active(), # Combined LC state from SM
                "long_A_busy": sound_manager_instance.channel_long_A.get_busy(),
                "long_A_sound": sound_manager_instance.get_sound_name_from_obj(sound_manager_instance.channel_long_A.get_sound()),
                "long_B_busy": sound_manager_instance.channel_long_B.get_busy(),
                "long_B_sound": sound_manager_instance.get_sound_name_from_obj(sound_manager_instance.channel_long_B.get_sound()),
                "long_transitioning": sound_manager_instance.transitioning_long_sound,
                "sim_time_@100thr": simulation.time_at_100_throttle,
                "sim_time_in_idle": simulation.time_in_idle,
                "sim_played_accel_rec": simulation.played_full_accel_sequence_recently,
                "sim_time_in_lc_range": simulation.time_in_launch_control_range,
                "sim_in_pot_gesture": simulation.in_potential_gesture,
                "sim_peak_thr_gesture": simulation.peak_throttle_in_gesture,
                "sim_last_blip_time": simulation.last_light_blip_played_time,
                "sim_gesture_lockout_until": simulation.gesture_lockout_until_time # Log new lockout time
            }
            log_data.append(log_entry)

            if current_time_loop - last_display_update_time >= DISPLAY_UPDATE_INTERVAL:
                update_display(
                    simulation.state,
                    smoothed_throttle_percentage, 
                    raw_throttle_percentage,      
                    raw_adc,
                    simulation.time_in_launch_control_range,
                    sound_manager_instance.idle_current_volume,
                    sound_manager_instance.is_launch_control_active(), # Use SM's perspective for display
                    sound_manager_instance.get_active_blip_count() 
                )
                last_display_update_time = current_time_loop

            # Frame rate limiting
            processing_time = time.time() - current_time_loop
            sleep_duration = max(0, (1.0 / FPS) - processing_time)
            time.sleep(sleep_duration)

    except Exception as e:
        print(f"\r{' ' * 145}\r", end='', flush=True) # Clear current display line
        print(f"\nUNEXPECTED ERROR in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\r{' ' * 145}\r", end='', flush=True) # Clear display line again
        print("\nInitiating final cleanup...")
        
        # Save log data to CSV
        if log_data:
            print(f"Writing log data to {LOG_FILE_NAME}...")
            try:
                field_names = set()
                for entry in log_data:
                    field_names.update(entry.keys())
                
                preferred_order = [
                    "timestamp_unix", "datetime_iso", "dt", "state", "raw_adc",
                    "raw_throttle_input_pct", "smoothed_throttle_pct", "sim_current_throttle_pct",
                    "idle_target_vol", "idle_current_vol", "idle_is_fading", "idle_chan_busy",
                    "active_blip_count", "sfx_chan_busy", "sfx_chan_sound",
                    "sm_lc_sounds_active", "sm_waiting_for_lc_hold", "sm_is_lc_active_overall",
                    "long_A_busy", "long_A_sound", "long_B_busy", "long_B_sound", "long_transitioning",
                    "sim_time_@100thr", "sim_time_in_idle", "sim_played_accel_rec",
                    "sim_time_in_lc_range", "sim_in_pot_gesture", "sim_peak_thr_gesture",
                    "sim_last_blip_time", "sim_gesture_lockout_until"
                ]
                final_fieldnames = [f for f in preferred_order if f in field_names]
                final_fieldnames.extend(sorted([f for f in field_names if f not in final_fieldnames]))

                with open(LOG_FILE_NAME, 'w', newline='') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=final_fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(log_data)
                print(f"Log successfully written to {LOG_FILE_NAME}")
            except Exception as e_csv:
                print(f"Error writing CSV log: {e_csv}")
        else:
            print("No log data to write.")

        # Stop all sounds and quit Pygame
        if 'sound_manager_instance' in locals() and sound_manager_instance and pygame.mixer.get_init():
            print("Stopping sounds...")
            sound_manager_instance.stop_launch_control_sequence(fade_ms=100) # Fade out LC if active
            sound_manager_instance.stop_idle()
            sound_manager_instance.stop_long_sequence(fade_ms=100) # Fade out long sequences
            sound_manager_instance.stop_all_light_blips()
            sound_manager_instance.stop_turbo_limiter_sfx() # Stop other SFX
            time.sleep(0.2) # Allow time for fadeouts to complete
        
        if pygame.mixer.get_init(): pygame.mixer.quit()
        if pygame.get_init(): pygame.quit() # Quit Pygame itself
        print("Shutdown complete.")

if __name__ == '__main__':
    main()