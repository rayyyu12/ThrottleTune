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
    import RPi.GPIO as GPIO
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

# Button Configuration
BUTTON_GPIO_PIN = 17
BUTTON_LONG_PRESS_TIME = 2.0
BUTTON_DEBOUNCE_TIME = 0.1

MIXER_FREQUENCY = 44100
MIXER_SIZE = -16
MIXER_CHANNELS_STEREO = 2
MIXER_BUFFER = 512
NUM_PYGAME_MIXER_CHANNELS = 25 # Increased for triple car system (M4=5, Supra=4, Hellcat=10, buffer=6)

# Common parameters
THROTTLE_DEADZONE_LOW = 0.05
THROTTLE_SMOOTHING_WINDOW_SIZE = 5

# M4 specific parameters (preserved exactly from original)
M4_SUSTAINED_100_THROTTLE_TIME = 1.5
M4_GESTURE_WINDOW_TIME = 0.75
M4_GESTURE_MAX_POINTS = 20
M4_FADE_OUT_MS = 300
M4_CROSSFADE_DURATION_MS = 500
M4_IDLE_TRANSITION_SPEED = 2.5
M4_TURBO_BOV_COOLDOWN = 1.0 # Cooldown for non-gesture turbo SFX if used elsewhere
M4_HIGH_REV_LIMITER_COOLDOWN = 1.5 # Cooldown for non-gesture limiter SFX if used elsewhere
M4_FULL_ACCEL_RESET_IDLE_TIME = 3.0
M4_NORMAL_IDLE_VOLUME = 0.7
M4_LOW_IDLE_VOLUME_DURING_SFX = 0.15 # For turbo/limiter if played outside gestures
M4_VERY_LOW_IDLE_VOLUME_DURING_LAUNCH = 0.05
MASTER_ENGINE_VOL = 0.02 # Overall engine sound volume (production level)
M4_STAGED_REV_VOLUME = 0.9 # Volume for new staged revs relative to master
M4_LAUNCH_CONTROL_THROTTLE_MIN = 0.55
M4_LAUNCH_CONTROL_THROTTLE_MAX = 0.85
M4_LAUNCH_CONTROL_HOLD_DURATION = 0.5
M4_LAUNCH_CONTROL_BRAKE_REQUIRED = False
M4_LAUNCH_CONTROL_ENGAGE_VOL = 1.0
M4_LAUNCH_CONTROL_HOLD_VOL = 1.0
M4_GESTURE_RETRIGGER_LOCKOUT = 0.3 # Min time after any gesture (incl. new revs) before new one
M4_ACCELERATION_SOUND_OFFSET = 0.5 # Seconds to skip at start of acceleration sounds to avoid silence

# --- M4 Moving Average Parameters ---
M4_RPM_IDLE = 800
M4_RPM_DECAY_RATE_PER_SEC = 1500  # How fast RPM drops when not revving
M4_RPM_DECAY_COOLDOWN_AFTER_REV = 0.1 # Seconds after rev sound finishes before RPM starts decaying
M4_RPM_RESET_TO_IDLE_THRESHOLD_TIME = 6.0 # Seconds of inactivity after a rev to fully reset RPM to idle for next base

# Supra specific parameters (ENHANCED from simulator)
SUPRA_NORMAL_IDLE_VOLUME = 0.7  # Match M4 volume level
SUPRA_LOW_IDLE_VOLUME_DURING_REV = 0.2
SUPRA_REV_GESTURE_WINDOW_TIME = 0.75
SUPRA_REV_RETRIGGER_LOCKOUT = 0.5
SUPRA_CLIP_OVERLAP_PREVENTION_TIME = 0.2  # Reduced overlap prevention time
SUPRA_PRE_ACCEL_DELAY = 0.15  # Grace period to determine user intent
SUPRA_CROSSFADE_DURATION_MS = 800
SUPRA_IDLE_TRANSITION_SPEED = 2.5
SUPRA_CRUISE_TRANSITION_DELAY = 0.75  # Time before transitioning to cruise after pull/push (750ms)
SUPRA_HIGHWAY_CRUISE_THRESHOLD = 0.90  # Throttle threshold for highway cruise
SUPRA_STAGED_REV_VOLUME = 0.9

# EMA Throttle Parameters (NEW from simulator)
SUPRA_EMA_ALPHA = 0.3  # EMA smoothing factor (0 = no smoothing, 1 = no filtering)

# Supra RPM simulation parameters (NEW from simulator)
SUPRA_RPM_IDLE = 900
SUPRA_RPM_DECAY_RATE_PER_SEC = 1200
SUPRA_RPM_DECAY_COOLDOWN_AFTER_REV = 0.1
SUPRA_RPM_RESET_TO_IDLE_THRESHOLD_TIME = 6.0

# Hellcat specific parameters
HELLCAT_NORMAL_IDLE_VOLUME = 0.7
HELLCAT_LOW_IDLE_VOLUME_DURING_SHIFT = 0.3
HELLCAT_CROSSFADE_DURATION = 500  # milliseconds
HELLCAT_THROTTLE_IDLE_THRESHOLD = 0.05
HELLCAT_FADE_IN_DURATION = 150  # milliseconds
HELLCAT_FADE_OUT_DURATION = 300  # milliseconds

# Hellcat Virtual Engine Physics (Tuned for Electric Scooter Operation)
HELLCAT_RPM_ACCEL_BASE = 1200          # Reduced from 4000 - much more realistic acceleration
HELLCAT_RPM_DECAY_COAST = 2000         # Increased from 1000 - faster natural decay  
HELLCAT_RPM_THROTTLE_LIFT_DECAY = 3500 # NEW - Aggressive engine braking on throttle release
HELLCAT_IDLE_RPM = 750
HELLCAT_REDLINE_RPM = 6200

# Hellcat Gear-specific behavior (Adjusted for longer gear hold times)
HELLCAT_GEAR_ACCEL_MULTIPLIERS = {1: 1.2, 2: 0.9, 3: 0.7, 4: 0.5, 5: 0.4}  # Reduced multipliers
HELLCAT_GEAR_ENGINE_BRAKING = {1: 2000, 2: 1500, 3: 1200, 4: 800, 5: 600}   # Increased braking
HELLCAT_GEAR_DOWNSHIFT_THRESHOLDS = {2: 1400, 3: 1800, 4: 2200, 5: 2800}    # Higher thresholds

# Hellcat Audio Inertia (NEW - for smoother sound transitions)
HELLCAT_AUDIO_INERTIA_SPEED = 3.0      # How fast audio volumes chase their targets
HELLCAT_MIN_SHIFT_INTERVAL = 2.5       # Increased from 1.5 - longer between shifts

# EMA Throttle Parameters for Hellcat
HELLCAT_EMA_ALPHA = 0.2  # EMA smoothing factor (0 = no smoothing, 1 = no filtering)

# --- M4 Channel Definitions (preserved exactly) ---
M4_CH_IDLE = 0
M4_CH_TURBO_LIMITER_SFX = 1 # For non-gesture turbo/limiter sounds, and LC engage/hold
M4_CH_LONG_SEQUENCE_A = 2
M4_CH_LONG_SEQUENCE_B = 3
M4_CH_STAGED_REV_SOUND = 4 # Dedicated channel for the new staged rev sounds

# --- Supra Channel Definitions ---
SUPRA_CH_IDLE = 5
SUPRA_CH_DRIVING_A = 6
SUPRA_CH_DRIVING_B = 7
SUPRA_CH_REV_SFX = 8

# --- Hellcat Channel Definitions ---
# Foundation Layer
HELLCAT_CH_IDLE = 9
HELLCAT_CH_RUMBLE_LOW = 10
HELLCAT_CH_RUMBLE_MID = 11
HELLCAT_CH_WHINE_LOW_A = 12
HELLCAT_CH_WHINE_LOW_B = 13
HELLCAT_CH_WHINE_HIGH_A = 14
HELLCAT_CH_WHINE_HIGH_B = 15

# Character Layer
HELLCAT_CH_ACCEL_RESPONSE = 16
HELLCAT_CH_DECEL_BURBLE = 17

# SFX Layer
HELLCAT_CH_STARTUP = 18
HELLCAT_CH_SHIFT_SFX = 19

# Sound file paths
M4_SOUND_FILES_PATH = "m4"
SUPRA_SOUND_FILES_PATH = "supra"
HELLCAT_SOUND_FILES_PATH = "hellcat"

# Logging and Display
DISPLAY_UPDATE_INTERVAL = 0.1
LOG_FILE_NAME = "dual_car_sound_log.csv"

# Global variables
adc_throttle_channel = None
current_car = "M4"  # Start with M4
running_script = True
log_data = []
button_pressed_time = None
last_button_state = False

def initialize_adc():
    global adc_throttle_channel
    if not RASPI_HW_AVAILABLE:
        print("ADC hardware modules not available. Cannot initialize ADC.")
        return False
    try:
        spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)
        cs = digitalio.DigitalInOut(board.D8)
        mcp = MCP.MCP3008(spi, cs)
        adc_throttle_channel = AnalogIn(mcp, getattr(MCP, f"P{ADC_CHANNEL_NUMBER}"))
        print(f"MCP3008 ADC initialized on channel P{ADC_CHANNEL_NUMBER}.")
        return True
    except Exception as e:
        print(f"FATAL ERROR initializing ADC: {e}")
        adc_throttle_channel = None
        return False

def initialize_button():
    if not RASPI_HW_AVAILABLE:
        print("GPIO hardware not available. Button disabled.")
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUTTON_GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        print(f"Button initialized on GPIO {BUTTON_GPIO_PIN}")
        return True
    except Exception as e:
        print(f"Error initializing button: {e}")
        return False

def read_adc_value():
    global adc_throttle_channel
    if adc_throttle_channel:
        try:
            return adc_throttle_channel.value
        except Exception:
            return MIN_ADC_VALUE
    else:
        return MIN_ADC_VALUE

def get_throttle_percentage_from_adc(raw_adc_value):
    if MAX_ADC_VALUE == MIN_ADC_VALUE: return 0.0
    clamped_value = max(MIN_ADC_VALUE, min(raw_adc_value, MAX_ADC_VALUE))
    percentage = (clamped_value - MIN_ADC_VALUE) / (MAX_ADC_VALUE - MIN_ADC_VALUE)
    return percentage

class M4SoundManager:
    def __init__(self):
        self.sounds = {}
        self.rev_stages = [] # For new staged revs
        self.load_sounds()
        self.channel_idle = pygame.mixer.Channel(M4_CH_IDLE)
        self.channel_turbo_limiter_sfx = pygame.mixer.Channel(M4_CH_TURBO_LIMITER_SFX)
        
        self.channel_staged_rev = None
        if pygame.mixer.get_init() and pygame.mixer.get_num_channels() > M4_CH_STAGED_REV_SOUND:
            self.channel_staged_rev = pygame.mixer.Channel(M4_CH_STAGED_REV_SOUND)
            print(f"M4 initialized dedicated channel {M4_CH_STAGED_REV_SOUND} for staged rev sounds.")
        else:
            mixer_channels = pygame.mixer.get_num_channels() if pygame.mixer.get_init() else 'Mixer not init'
            print(f"M4 Warning: Not enough mixer channels ({mixer_channels}) for dedicated staged rev channel ({M4_CH_STAGED_REV_SOUND}). Revs may not play.")

        self.idle_target_volume = M4_NORMAL_IDLE_VOLUME
        self.idle_current_volume = M4_NORMAL_IDLE_VOLUME
        self.idle_is_fading = False

        self.waiting_for_launch_hold_loop = False
        self.launch_control_sounds_active = False
        self.just_switched_to_lc_hold = False # Flag to prevent immediate deactivation
        self.channel_long_A = pygame.mixer.Channel(M4_CH_LONG_SEQUENCE_A)
        self.channel_long_B = pygame.mixer.Channel(M4_CH_LONG_SEQUENCE_B)
        self.active_long_channel = self.channel_long_A
        self.transitioning_long_sound = False
        self.transition_start_time = 0
        
        # For sound offset functionality
        self.pending_offset_sounds = []  # List of (sound_key, start_time, offset_duration, loops, channel_type)

    def _load_sound_with_duration(self, filename):
        path = os.path.join(M4_SOUND_FILES_PATH, filename)
        if os.path.exists(path):
            try:
                sound = pygame.mixer.Sound(path)
                return sound, sound.get_length()
            except pygame.error as e:
                print(f"M4 Warning: Could not load '{filename}': {e}")
                return None, 0
        print(f"M4 Warning: Sound file not found '{filename}' at '{path}'")
        return None, 0

    def load_sounds(self):
        self.sounds['idle'], _ = self._load_sound_with_duration("engine_idle_loop.wav")

        # New Staged Rev Sounds
        # Each stage: key, sound object, peak RPM it represents, duration
        snd, dur = self._load_sound_with_duration("engine_rev_stage1.wav") # Idle to ~3k RPM
        self.rev_stages.append({'key': 'rev_stage1', 'sound': snd, 'rpm_peak': 3000, 'duration': dur})
        snd, dur = self._load_sound_with_duration("engine_rev_stage2.wav") # ~3k to ~5k RPM
        self.rev_stages.append({'key': 'rev_stage2', 'sound': snd, 'rpm_peak': 5000, 'duration': dur})
        snd, dur = self._load_sound_with_duration("engine_rev_stage3.wav") # ~5k to ~7k RPM
        self.rev_stages.append({'key': 'rev_stage3', 'sound': snd, 'rpm_peak': 7000, 'duration': dur})
        snd, dur = self._load_sound_with_duration("engine_rev_stage4.wav") # ~7k to Redline (e.g. previous rev_limiter sound)
        self.rev_stages.append({'key': 'rev_stage4', 'sound': snd, 'rpm_peak': 8500, 'duration': dur})

        self.sounds['turbo_bov'], _ = self._load_sound_with_duration("turbo_spool_and_bov.wav")
        self.sounds['rev_limiter'], _ = self._load_sound_with_duration("engine_high_rev_with_limiter.wav") # Still available if needed elsewhere
        
        self.sounds['accel_gears'], _ = self._load_sound_with_duration("acceleration_gears_1_to_4.wav")
        self.sounds['cruising'], _ = self._load_sound_with_duration("engine_cruising_loop.wav")
        self.sounds['decel_downshifts'], _ = self._load_sound_with_duration("deceleration_downshifts_to_idle.wav")
        self.sounds['starter'], _ = self._load_sound_with_duration("engine_starter.wav")
        self.sounds['launch_control_engage'], _ = self._load_sound_with_duration("launch_control_engage.wav")
        self.sounds['launch_control_hold_loop'], _ = self._load_sound_with_duration("launch_control_hold_loop.wav")

    def get_sound_name_from_obj(self, sound_obj):
        if sound_obj is None: return "None"
        for name, sound_asset_tuple in self.sounds.items():
            if name == 'idle': # idle is loaded directly
                if self.sounds['idle'] == sound_obj: return "idle"
                continue
            if isinstance(sound_asset_tuple, pygame.mixer.Sound) and sound_asset_tuple == sound_obj:
                 return name
        for stage in self.rev_stages:
            if stage['sound'] == sound_obj:
                return stage['key']
        return "UnknownSoundObject"

    def update(self):
        # Reset the flag at the beginning of each update cycle
        self.just_switched_to_lc_hold = False
        
        # Handle pending offset sounds
        current_time = time.time()
        sounds_to_remove = []
        for i, (sound_key, start_time, offset_duration, loops, channel_type) in enumerate(self.pending_offset_sounds):
            if current_time >= start_time + offset_duration:
                # Time to start the sound with offset
                sound_info = self.sounds.get(sound_key)
                if sound_info and channel_type == 'long':
                    # Create a subsound starting at the offset
                    try:
                        # For pygame, we'll simulate offset by playing and then seeking
                        # Since pygame doesn't support seeking, we'll note this in comments
                        # The actual offset implementation would need audio library support
                        self.active_long_channel.set_volume(MASTER_ENGINE_VOL)
                        self.active_long_channel.play(sound_info, loops=loops)
                        print(f"M4 Playing {sound_key} with {offset_duration}s offset simulation")
                    except Exception as e:
                        print(f"M4 Error playing offset sound {sound_key}: {e}")
                sounds_to_remove.append(i)
        
        # Remove processed sounds
        for i in reversed(sounds_to_remove):
            self.pending_offset_sounds.pop(i)

        lc_engage_sound = self.sounds.get('launch_control_engage')
        lc_hold_sound = self.sounds.get('launch_control_hold_loop')
        current_sfx_sound_at_call = self.channel_turbo_limiter_sfx.get_sound() # Snapshot

        if self.waiting_for_launch_hold_loop:
            if not self.channel_turbo_limiter_sfx.get_busy() or current_sfx_sound_at_call != lc_engage_sound:
                if lc_hold_sound:
                    self.channel_turbo_limiter_sfx.set_volume(M4_LAUNCH_CONTROL_HOLD_VOL * MASTER_ENGINE_VOL)
                    self.channel_turbo_limiter_sfx.play(lc_hold_sound, loops=-1)
                    self.just_switched_to_lc_hold = True # Set flag after successfully starting hold loop
                else:
                    self.launch_control_sounds_active = False
                self.waiting_for_launch_hold_loop = False
        
        # This check ensures LC SFX active status is correctly maintained or deactivated
        if self.launch_control_sounds_active and not self.just_switched_to_lc_hold:
            # Get the current sound again, as it might have changed if hold loop just started
            sfx_sound_now = self.channel_turbo_limiter_sfx.get_sound() 
            sfx_channel_busy_now = self.channel_turbo_limiter_sfx.get_busy()

            if not self.waiting_for_launch_hold_loop and \
               (not sfx_channel_busy_now or \
                (sfx_sound_now != lc_engage_sound and sfx_sound_now != lc_hold_sound)):
                self.launch_control_sounds_active = False

    def play_idle(self):
        idle_sound = self.sounds.get('idle')
        if idle_sound:
            if not self.channel_idle.get_busy() or self.channel_idle.get_sound() != idle_sound:
                self.channel_idle.play(idle_sound, loops=-1)
            self.idle_current_volume = self.idle_target_volume
            self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
            self.idle_is_fading = abs(self.idle_current_volume - self.idle_target_volume) > 0.01

    def set_idle_target_volume(self, target_volume, instant=False):
        target_volume = max(0.0, min(1.0, target_volume))
        if abs(self.idle_target_volume - target_volume) > 0.01 or instant :
            self.idle_target_volume = target_volume
            if instant:
                self.idle_current_volume = target_volume
                if self.channel_idle.get_sound():
                     self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
                self.idle_is_fading = False
            else:
                if abs(self.idle_current_volume - self.idle_target_volume) > 0.01:
                    self.idle_is_fading = True

    def update_idle_fade(self, dt):
        if self.idle_is_fading and self.channel_idle.get_busy():
            if abs(self.idle_current_volume - self.idle_target_volume) < 0.01:
                self.idle_current_volume = self.idle_target_volume
                self.idle_is_fading = False
            elif self.idle_current_volume < self.idle_target_volume:
                self.idle_current_volume = min(self.idle_current_volume + M4_IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            else:
                self.idle_current_volume = max(self.idle_current_volume - M4_IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            
            if self.channel_idle.get_sound():
                self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)

    def stop_idle(self):
        self.channel_idle.stop()
        self.idle_is_fading = False

    def play_staged_rev(self, current_rpm, gesture_peak_throttle):
        if not self.channel_staged_rev or self.channel_staged_rev.get_busy():
            return None # Rev channel not available or busy

        selected_stage_info = None
        if gesture_peak_throttle <= 0.1: 
             if current_rpm > M4_RPM_IDLE + 500: return None 
        
        if current_rpm < self.rev_stages[0]['rpm_peak'] * 0.8: 
            if gesture_peak_throttle < 0.4:
                selected_stage_info = self.rev_stages[0]
            elif gesture_peak_throttle < 0.75:
                selected_stage_info = self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0]
            else:
                selected_stage_info = self.rev_stages[2] if len(self.rev_stages) > 2 else (self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0])
        elif current_rpm < self.rev_stages[1]['rpm_peak'] * 0.8: 
            if gesture_peak_throttle < 0.5:
                selected_stage_info = self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0]
            else:
                selected_stage_info = self.rev_stages[2] if len(self.rev_stages) > 2 else (self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0])
        elif current_rpm < self.rev_stages[2]['rpm_peak'] * 0.9: 
            if gesture_peak_throttle < 0.6:
                 selected_stage_info = self.rev_stages[2] if len(self.rev_stages) > 2 else self.rev_stages[-1]
            else:
                 selected_stage_info = self.rev_stages[3] if len(self.rev_stages) > 3 else self.rev_stages[-1]
        else: 
            selected_stage_info = self.rev_stages[3] if len(self.rev_stages) > 3 else self.rev_stages[-1]

        if selected_stage_info and selected_stage_info['sound']:
            if selected_stage_info['rpm_peak'] < current_rpm and selected_stage_info != self.rev_stages[-1]:
                for stage in self.rev_stages:
                    if stage['rpm_peak'] >= current_rpm:
                        selected_stage_info = stage
                        break
                else: 
                    selected_stage_info = self.rev_stages[-1]

            print(f"M4 Playing rev: {selected_stage_info['key']} (Peak: {selected_stage_info['rpm_peak']}) | CurrentRPM: {current_rpm:.0f} | Gesture: {gesture_peak_throttle:.2f}")
            self.channel_staged_rev.set_volume(M4_STAGED_REV_VOLUME * MASTER_ENGINE_VOL)
            self.channel_staged_rev.play(selected_stage_info['sound'])
            return {'key': selected_stage_info['key'], 'rpm_peak': selected_stage_info['rpm_peak'], 'duration': selected_stage_info['duration']}
        return None

    def play_turbo_or_limiter_sfx(self, sound_key): 
        sound_to_play = self.sounds.get(sound_key)
        if sound_to_play:
            if self.is_launch_control_active():
                self.stop_launch_control_sequence(fade_ms=100)
            self.channel_turbo_limiter_sfx.set_volume(MASTER_ENGINE_VOL)
            self.channel_turbo_limiter_sfx.play(sound_to_play)
            return True
        return False

    def play_starter_sfx(self):
        sound_to_play = self.sounds.get('starter')
        if sound_to_play:
            current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
            lc_engage = self.sounds.get('launch_control_engage')
            lc_hold = self.sounds.get('launch_control_hold_loop')
            if not self.channel_turbo_limiter_sfx.get_busy() or \
               (current_sfx_sound != lc_engage and current_sfx_sound != lc_hold):
                self.channel_turbo_limiter_sfx.stop()
                self.channel_turbo_limiter_sfx.set_volume(MASTER_ENGINE_VOL)
                self.channel_turbo_limiter_sfx.play(sound_to_play)
                return True
        return False

    def stop_turbo_limiter_sfx(self): 
        current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
        lc_engage = self.sounds.get('launch_control_engage')
        lc_hold = self.sounds.get('launch_control_hold_loop')
        if current_sfx_sound != lc_engage and current_sfx_sound != lc_hold:
            self.channel_turbo_limiter_sfx.stop()

    def is_turbo_limiter_sfx_busy(self): 
        if self.channel_turbo_limiter_sfx.get_busy():
            current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
            lc_engage = self.sounds.get('launch_control_engage')
            lc_hold = self.sounds.get('launch_control_hold_loop')
            if current_sfx_sound != lc_engage and current_sfx_sound != lc_hold:
                return True
        return False

    def any_playful_sfx_active(self):
        if self.channel_staged_rev and self.channel_staged_rev.get_busy():
            return True
        if self.channel_turbo_limiter_sfx.get_busy():
            current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
            non_playful_sounds = [
                self.sounds.get('launch_control_engage'), 
                self.sounds.get('launch_control_hold_loop'),
                self.sounds.get('starter')
            ]
            if current_sfx_sound not in non_playful_sounds and current_sfx_sound is not None:
                return True
        return False

    def stop_staged_rev_sound(self):
        if self.channel_staged_rev:
            self.channel_staged_rev.stop()

    def play_launch_control_sequence(self):
        engage_sound = self.sounds.get('launch_control_engage')
        hold_sound = self.sounds.get('launch_control_hold_loop')
        if engage_sound:
            self.channel_turbo_limiter_sfx.stop()
            self.channel_turbo_limiter_sfx.set_volume(M4_LAUNCH_CONTROL_ENGAGE_VOL * MASTER_ENGINE_VOL)
            self.channel_turbo_limiter_sfx.play(engage_sound)
            self.waiting_for_launch_hold_loop = True
            self.launch_control_sounds_active = True
            self.just_switched_to_lc_hold = False # Ensure it's false when starting engage
            return True
        elif hold_sound:
            print("M4 Launch control engage sound missing, playing hold loop directly.")
            self.channel_turbo_limiter_sfx.stop()
            self.channel_turbo_limiter_sfx.set_volume(M4_LAUNCH_CONTROL_HOLD_VOL * MASTER_ENGINE_VOL)
            self.channel_turbo_limiter_sfx.play(hold_sound, loops=-1)
            self.waiting_for_launch_hold_loop = False
            self.launch_control_sounds_active = True
            self.just_switched_to_lc_hold = True # Switched directly to hold
            return True
        self.launch_control_sounds_active = False 
        return False

    def stop_launch_control_sequence(self, fade_ms=M4_FADE_OUT_MS // 2):
        current_sfx_sound = self.channel_turbo_limiter_sfx.get_sound()
        lc_engage = self.sounds.get('launch_control_engage')
        lc_hold = self.sounds.get('launch_control_hold_loop')
        if self.channel_turbo_limiter_sfx.get_busy() and \
           (current_sfx_sound == lc_engage or current_sfx_sound == lc_hold):
            if fade_ms > 0: self.channel_turbo_limiter_sfx.fadeout(fade_ms)
            else: self.channel_turbo_limiter_sfx.stop()
        self.waiting_for_launch_hold_loop = False
        self.launch_control_sounds_active = False
        self.just_switched_to_lc_hold = False

    def is_launch_control_active(self):
        return self.launch_control_sounds_active or self.waiting_for_launch_hold_loop
    
    def play_long_sequence(self, sound_key, loops=0, transition_from_other=False, start_offset=0.0):
        sound_info = self.sounds.get(sound_key)
        if not sound_info : 
            print(f"M4 Long sequence sound key '{sound_key}' not found or not a direct sound object.")
            other_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A
            other_channel.stop()
            self.active_long_channel.stop()
            self.transitioning_long_sound = False
            return

        sound_to_play = sound_info 

        # Handle offset sounds by scheduling them
        if start_offset > 0.0:
            print(f"M4 Scheduling {sound_key} with {start_offset}s offset")
            self.pending_offset_sounds.append((sound_key, time.time(), start_offset, loops, 'long'))
            return

        if not transition_from_other:
            other_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A
            other_channel.stop()
            self.active_long_channel.set_volume(MASTER_ENGINE_VOL)
            self.active_long_channel.play(sound_to_play, loops=loops)
            self.transitioning_long_sound = False
        else:
            fade_out_channel = self.active_long_channel
            fade_in_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A
            fade_out_channel.fadeout(M4_CROSSFADE_DURATION_MS)
            fade_in_channel.set_volume(0)
            fade_in_channel.play(sound_to_play, loops=loops)
            self.active_long_channel = fade_in_channel
            self.transitioning_long_sound = True
            self.transition_start_time = time.time()

    def update_long_sequence_crossfade(self):
        if self.transitioning_long_sound:
            elapsed_time_ms = (time.time() - self.transition_start_time) * 1000
            progress = min(1.0, elapsed_time_ms / M4_CROSSFADE_DURATION_MS)
            if self.active_long_channel.get_busy():
                 self.active_long_channel.set_volume(progress * MASTER_ENGINE_VOL)
            if progress >= 1.0:
                self.transitioning_long_sound = False
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

    def stop_all_sounds(self):
        self.channel_idle.stop()
        self.channel_turbo_limiter_sfx.stop()
        self.channel_long_A.stop()
        self.channel_long_B.stop()
        if self.channel_staged_rev:
            self.channel_staged_rev.stop()
        self.transitioning_long_sound = False
        self.launch_control_sounds_active = False
        self.waiting_for_launch_hold_loop = False
        self.idle_is_fading = False

    def fade_out_all_sounds(self, fade_ms):
        if self.channel_idle.get_busy():
            self.channel_idle.fadeout(fade_ms)
        if self.channel_turbo_limiter_sfx.get_busy():
            self.channel_turbo_limiter_sfx.fadeout(fade_ms)
        if self.channel_long_A.get_busy():
            self.channel_long_A.fadeout(fade_ms)
        if self.channel_long_B.get_busy():
            self.channel_long_B.fadeout(fade_ms)
        if self.channel_staged_rev and self.channel_staged_rev.get_busy():
            self.channel_staged_rev.fadeout(fade_ms)

# ENHANCED Supra Sound Manager (from simulator)
class SupraSoundManager:
    def __init__(self):
        self.sounds = {}
        self.load_sounds()
        self.channel_idle = pygame.mixer.Channel(SUPRA_CH_IDLE)
        self.channel_driving_A = pygame.mixer.Channel(SUPRA_CH_DRIVING_A)
        self.channel_driving_B = pygame.mixer.Channel(SUPRA_CH_DRIVING_B)
        self.channel_rev_sfx = pygame.mixer.Channel(SUPRA_CH_REV_SFX)
        
        self.active_driving_channel = self.channel_driving_A
        self.idle_target_volume = SUPRA_NORMAL_IDLE_VOLUME
        self.idle_current_volume = SUPRA_NORMAL_IDLE_VOLUME
        self.idle_is_fading = False
        
        # Crossfading system (NEW from simulator)
        self.transitioning_driving_sound = False
        self.transition_start_time = 0
        
        # State tracking
        self.last_clip_start_time = 0

    def _load_sound_with_duration(self, filename):
        path = os.path.join(SUPRA_SOUND_FILES_PATH, filename)
        if os.path.exists(path):
            try:
                sound = pygame.mixer.Sound(path)
                return sound, sound.get_length()
            except pygame.error as e:
                print(f"Supra Warning: Could not load '{filename}': {e}")
                return None, 0
        print(f"Supra Warning: Sound file not found '{filename}' at '{path}'")
        return None, 0

    def load_sounds(self):
        # Core sounds (essential for basic functionality)
        essential_sounds = [
            ('idle', "supra_idle_loop.wav"),
            ('startup', "supra_startup.wav")
        ]
        
        # Load essential sounds and track failures
        missing_essential = []
        for key, filename in essential_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
            if self.sounds[key] is None:
                missing_essential.append(filename)
        
        if missing_essential:
            print(f"SUPRA CRITICAL ERROR: Missing essential sound files: {missing_essential}")
            print("Supra functionality will be severely impacted!")
        
        # Light pulls and cruising sounds (10-30% throttle)
        light_sounds = [
            ('light_pull_1', "light_pull_1.wav"),
            ('light_pull_2', "light_pull_2.wav"),
            ('light_cruise_1', "light_cruise_1.wav"),
            ('light_cruise_2', "light_cruise_2.wav"),
            ('light_cruise_3', "light_cruise_3.wav")
        ]
        
        for key, filename in light_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
        
        # Aggressive pushes (31-60% throttle)
        aggressive_sounds = [
            ('aggressive_push_1', "aggressive_push_1.wav"),
            ('aggressive_push_2', "aggressive_push_2.wav"),
            ('aggressive_push_3', "aggressive_push_3.wav"),
            ('aggressive_push_4', "aggressive_push_4.wav"),
            ('aggressive_push_5', "aggressive_push_5.wav"),
            ('aggressive_push_6', "aggressive_push_6.wav")
        ]
        
        for key, filename in aggressive_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
        
        # Violent pulls (61-100% throttle)
        violent_sounds = [
            ('violent_pull_1', "violent_pull_1.wav"),
            ('violent_pull_2', "violent_pull_2.wav"),
            ('violent_pull_3', "violent_pull_3.wav")
        ]
        
        for key, filename in violent_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
        
        # Highway cruise (optional)
        self.sounds['highway_cruise_loop'], _ = self._load_sound_with_duration("highway_cruise_loop.wav")
        
        # ENHANCED: Better categorization (from simulator)
        self.light_pull_sounds = ['light_pull_1', 'light_pull_2']
        self.light_cruise_sounds = ['light_cruise_1', 'light_cruise_2', 'light_cruise_3']
        self.aggressive_push_sounds = ['aggressive_push_1', 'aggressive_push_2', 'aggressive_push_3', 
                                      'aggressive_push_4', 'aggressive_push_5', 'aggressive_push_6']
        self.violent_pull_sounds = ['violent_pull_1', 'violent_pull_2', 'violent_pull_3']
        
        # ENHANCED: Staged Rev Sounds (NEW from simulator, adapted from M4 approach)
        self.rev_stages = []
        snd, dur = self._load_sound_with_duration("supra_rev_stage1.wav")
        self.rev_stages.append({'key': 'supra_rev_stage1', 'sound': snd, 'rpm_peak': 3500, 'duration': dur})
        snd, dur = self._load_sound_with_duration("supra_rev_stage2.wav")
        self.rev_stages.append({'key': 'supra_rev_stage2', 'sound': snd, 'rpm_peak': 5500, 'duration': dur})
        snd, dur = self._load_sound_with_duration("supra_rev_stage3.wav")
        self.rev_stages.append({'key': 'supra_rev_stage3', 'sound': snd, 'rpm_peak': 7500, 'duration': dur})
        snd, dur = self._load_sound_with_duration("supra_rev_stage4.wav")
        self.rev_stages.append({'key': 'supra_rev_stage4', 'sound': snd, 'rpm_peak': 9000, 'duration': dur})
        
        # Keep original rev sounds as fallback
        rev_sounds = [
            ('rev_1', "supra_rev_1.wav"),
            ('rev_2', "supra_rev_2.wav"),
            ('rev_3', "supra_rev_3.wav")
        ]
        
        for key, filename in rev_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
        
        print(f"SUPRA: Sound loading complete. Total sounds loaded: {len([s for s in self.sounds.values() if s is not None])}")

    def get_sound_name_from_obj(self, sound_obj):
        if sound_obj is None:
            return "None"
        for name, sound in self.sounds.items():
            if isinstance(sound, pygame.mixer.Sound) and sound == sound_obj:
                return name
        # Check staged rev sounds too
        for stage in self.rev_stages:
            if stage['sound'] == sound_obj:
                return stage['key']
        return "UnknownSoundObject"

    def set_idle_target_volume(self, target_volume, instant=False):
        target_volume = max(0.0, min(1.0, target_volume))
        if abs(self.idle_target_volume - target_volume) > 0.01 or instant:
            self.idle_target_volume = target_volume
            if instant:
                self.idle_current_volume = target_volume
                if self.channel_idle.get_sound():
                    self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
                self.idle_is_fading = False
            else:
                if abs(self.idle_current_volume - self.idle_target_volume) > 0.01:
                    self.idle_is_fading = True

    def update_idle_fade(self, dt):
        if self.idle_is_fading and self.channel_idle.get_busy():
            if abs(self.idle_current_volume - self.idle_target_volume) < 0.01:
                self.idle_current_volume = self.idle_target_volume
                self.idle_is_fading = False
            elif self.idle_current_volume < self.idle_target_volume:
                self.idle_current_volume = min(self.idle_current_volume + SUPRA_IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            else:
                self.idle_current_volume = max(self.idle_current_volume - SUPRA_IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            
            if self.channel_idle.get_sound():
                self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)

    def play_idle(self):
        idle_sound = self.sounds.get('idle')
        if idle_sound:
            if not self.channel_idle.get_busy() or self.channel_idle.get_sound() != idle_sound:
                self.channel_idle.play(idle_sound, loops=-1)
            self.idle_current_volume = self.idle_target_volume
            self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
            self.idle_is_fading = abs(self.idle_current_volume - self.idle_target_volume) > 0.01

    def stop_idle(self):
        self.channel_idle.stop()
        self.idle_is_fading = False

    # ENHANCED: New method from simulator
    def get_throttle_range(self, throttle):
        """Determine which throttle range we're in"""
        if throttle >= SUPRA_HIGHWAY_CRUISE_THRESHOLD:
            return 'highway'
        elif throttle >= 0.61:
            return 'violent'
        elif throttle >= 0.31:
            return 'aggressive'
        elif throttle >= 0.10:
            return 'light'
        else:
            return 'idle'
    
    # ENHANCED: Improved driving sound method from simulator
    def play_driving_sound(self, throttle_percentage, force_type=None, crossfade=False):
        """Play appropriate driving sound based on throttle and context"""
        current_time = time.time()
        
        # Check if we can play (unless crossfading)
        if not crossfade:
            if current_time - self.last_clip_start_time < SUPRA_CLIP_OVERLAP_PREVENTION_TIME:
                return False
            if self.channel_driving_A.get_busy() or self.channel_driving_B.get_busy():
                return False
        
        throttle_range = self.get_throttle_range(throttle_percentage)
        selected_sound = None
        sound_name = ""
        sound_type = force_type  # 'pull', 'push', 'cruise', 'highway_cruise'
        
        # Determine sound type if not forced
        if sound_type is None:
            sound_type = 'pull'  # Default to pull for initial acceleration
        
        # Select appropriate sound based on range and type
        if sound_type == 'highway_cruise':
            # Special case: Highway cruise uses dedicated highway_cruise_loop.wav
            if self.sounds.get('highway_cruise_loop'):
                selected_sound = self.sounds['highway_cruise_loop']
                sound_name = 'highway_cruise_loop'
                
        elif sound_type == 'cruise':
            # Use light_cruise for ALL ranges except highway
            if throttle_range == 'highway':
                # Highway range gets special highway cruise
                if self.sounds.get('highway_cruise_loop'):
                    selected_sound = self.sounds['highway_cruise_loop']
                    sound_name = 'highway_cruise_loop'
                    sound_type = 'highway_cruise'  # Update type
            else:
                # All other ranges (light, aggressive, violent) use light_cruise files
                available_sounds = [s for s in self.light_cruise_sounds if self.sounds.get(s)]
                if available_sounds:
                    sound_name = random.choice(available_sounds)
                    selected_sound = self.sounds[sound_name]
                
        else:  # pull/push sounds
            if throttle_range == 'light':
                available_sounds = [s for s in self.light_pull_sounds if self.sounds.get(s)]
            elif throttle_range == 'aggressive':
                available_sounds = [s for s in self.aggressive_push_sounds if self.sounds.get(s)]
            elif throttle_range == 'violent' or throttle_range == 'highway':
                available_sounds = [s for s in self.violent_pull_sounds if self.sounds.get(s)]
            else:
                available_sounds = []
            
            if available_sounds:
                sound_name = random.choice(available_sounds)
                selected_sound = self.sounds[sound_name]
        
        if selected_sound:
            target_channel = self.channel_driving_B if self.active_driving_channel == self.channel_driving_A else self.channel_driving_A
            
            if crossfade:
                # Crossfade implementation
                fade_out_channel = self.active_driving_channel
                fade_in_channel = target_channel
                
                fade_out_channel.fadeout(SUPRA_CROSSFADE_DURATION_MS)
                fade_in_channel.set_volume(0)
                
                loops = -1 if (sound_type == 'cruise' or sound_type == 'highway_cruise') else 0
                fade_in_channel.play(selected_sound, loops=loops)
                
                self.active_driving_channel = fade_in_channel
                self.transitioning_driving_sound = True
                self.transition_start_time = current_time
                
                print(f"Supra crossfading to: {sound_name} ({sound_type}) at {throttle_percentage:.2f}")
            else:
                # Normal play
                loops = -1 if (sound_type == 'cruise' or sound_type == 'highway_cruise') else 0
                target_channel.set_volume(MASTER_ENGINE_VOL)
                target_channel.play(selected_sound, loops=loops)
                self.active_driving_channel = target_channel
                
                print(f"Supra playing: {sound_name} ({sound_type}) at {throttle_percentage:.2f}")
            
            # Update state tracking
            self.current_throttle_range = throttle_range
            self.current_sound_type = sound_type
            self.last_clip_start_time = current_time
            
            return True
        
        return False

    # ENHANCED: New staged rev method from simulator
    def play_staged_rev(self, current_rpm, gesture_peak_throttle):
        if self.channel_rev_sfx.get_busy():
            return None

        selected_stage_info = None
        if gesture_peak_throttle <= 0.1: 
             if current_rpm > SUPRA_RPM_IDLE + 500: return None 
        
        if current_rpm < self.rev_stages[0]['rpm_peak'] * 0.8: 
            if gesture_peak_throttle < 0.4:
                selected_stage_info = self.rev_stages[0]
            elif gesture_peak_throttle < 0.75:
                selected_stage_info = self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0]
            else:
                selected_stage_info = self.rev_stages[2] if len(self.rev_stages) > 2 else (self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0])
        elif current_rpm < self.rev_stages[1]['rpm_peak'] * 0.8: 
            if gesture_peak_throttle < 0.5:
                selected_stage_info = self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0]
            else:
                selected_stage_info = self.rev_stages[2] if len(self.rev_stages) > 2 else (self.rev_stages[1] if len(self.rev_stages) > 1 else self.rev_stages[0])
        elif current_rpm < self.rev_stages[2]['rpm_peak'] * 0.9: 
            if gesture_peak_throttle < 0.6:
                 selected_stage_info = self.rev_stages[2] if len(self.rev_stages) > 2 else self.rev_stages[-1]
            else:
                 selected_stage_info = self.rev_stages[3] if len(self.rev_stages) > 3 else self.rev_stages[-1]
        else: 
            selected_stage_info = self.rev_stages[3] if len(self.rev_stages) > 3 else self.rev_stages[-1]

        if selected_stage_info and selected_stage_info['sound']:
            if selected_stage_info['rpm_peak'] < current_rpm and selected_stage_info != self.rev_stages[-1]:
                for stage in self.rev_stages:
                    if stage['rpm_peak'] >= current_rpm:
                        selected_stage_info = stage
                        break
                else: 
                    selected_stage_info = self.rev_stages[-1]

            print(f"Supra Playing rev: {selected_stage_info['key']} (Peak: {selected_stage_info['rpm_peak']}) | CurrentRPM: {current_rpm:.0f} | Gesture: {gesture_peak_throttle:.2f}")
            self.channel_rev_sfx.set_volume(SUPRA_STAGED_REV_VOLUME * MASTER_ENGINE_VOL)
            self.channel_rev_sfx.play(selected_stage_info['sound'])
            return {'key': selected_stage_info['key'], 'rpm_peak': selected_stage_info['rpm_peak'], 'duration': selected_stage_info['duration']}
        return None
    
    def play_rev_sound(self, peak_throttle):
        """Fallback method for simple rev sound playing (backwards compatibility)"""
        if self.channel_rev_sfx.get_busy():
            return False
        
        rev_sound = None
        sound_name = ""
        
        if peak_throttle < 0.4:
            rev_sound = self.sounds.get('rev_1')
            sound_name = "rev_1"
        elif peak_throttle < 0.7:
            rev_sound = self.sounds.get('rev_2')
            sound_name = "rev_2"
        else:
            rev_sound = self.sounds.get('rev_3')
            sound_name = "rev_3"
        
        if rev_sound:
            print(f"Supra playing rev: {sound_name} (peak throttle: {peak_throttle:.2f})")
            self.channel_rev_sfx.set_volume(MASTER_ENGINE_VOL)
            self.channel_rev_sfx.play(rev_sound)
            return True
        return False

    # ENHANCED: New crossfade update method from simulator
    def update_driving_crossfade(self):
        """Update crossfade transition for driving sounds"""
        if self.transitioning_driving_sound:
            elapsed_time_ms = (time.time() - self.transition_start_time) * 1000
            progress = min(1.0, elapsed_time_ms / SUPRA_CROSSFADE_DURATION_MS)
            
            if self.active_driving_channel.get_busy():
                self.active_driving_channel.set_volume(progress * MASTER_ENGINE_VOL)
            
            if progress >= 1.0:
                self.transitioning_driving_sound = False
                if self.active_driving_channel.get_busy():
                    self.active_driving_channel.set_volume(MASTER_ENGINE_VOL)
    
    def is_driving_sound_busy(self):
        return self.channel_driving_A.get_busy() or self.channel_driving_B.get_busy() or self.transitioning_driving_sound
    
    # ENHANCED: New method from simulator
    def stop_driving_sounds(self, fade_ms=0):
        """Stop all driving sounds with optional fade"""
        if fade_ms > 0:
            self.channel_driving_A.fadeout(fade_ms)
            self.channel_driving_B.fadeout(fade_ms)
        else:
            self.channel_driving_A.stop()
            self.channel_driving_B.stop()
        self.transitioning_driving_sound = False

    def is_rev_sound_busy(self):
        return self.channel_rev_sfx.get_busy()

    def play_startup_sound(self):
        startup_sound = self.sounds.get('startup')
        if startup_sound:
            # Use rev sfx channel for startup
            self.channel_rev_sfx.stop()
            self.channel_rev_sfx.set_volume(MASTER_ENGINE_VOL)
            self.channel_rev_sfx.play(startup_sound)
            return True
        return False

    def stop_all_sounds(self):
        self.channel_idle.stop()
        self.channel_driving_A.stop()
        self.channel_driving_B.stop()
        self.channel_rev_sfx.stop()
        self.idle_is_fading = False
        self.transitioning_driving_sound = False

    def fade_out_all_sounds(self, fade_ms):
        if self.channel_idle.get_busy():
            self.channel_idle.fadeout(fade_ms)
        if self.channel_driving_A.get_busy():
            self.channel_driving_A.fadeout(fade_ms)
        if self.channel_driving_B.get_busy():
            self.channel_driving_B.fadeout(fade_ms)
        if self.channel_rev_sfx.get_busy():
            self.channel_rev_sfx.fadeout(fade_ms)

class HellcatSoundManager:
    def __init__(self):
        self.sounds = {}
        self.load_sounds()
        
        # Foundation Layer channels
        self.channel_idle = pygame.mixer.Channel(HELLCAT_CH_IDLE)
        self.channel_rumble_low = pygame.mixer.Channel(HELLCAT_CH_RUMBLE_LOW)
        self.channel_rumble_mid = pygame.mixer.Channel(HELLCAT_CH_RUMBLE_MID)
        
        # Supercharger whine crossfading channels
        self.channel_whine_low_a = pygame.mixer.Channel(HELLCAT_CH_WHINE_LOW_A)
        self.channel_whine_low_b = pygame.mixer.Channel(HELLCAT_CH_WHINE_LOW_B)
        self.channel_whine_high_a = pygame.mixer.Channel(HELLCAT_CH_WHINE_HIGH_A)
        self.channel_whine_high_b = pygame.mixer.Channel(HELLCAT_CH_WHINE_HIGH_B)
        
        # Character Layer channels
        self.channel_accel_response = pygame.mixer.Channel(HELLCAT_CH_ACCEL_RESPONSE)
        self.channel_decel_burble = pygame.mixer.Channel(HELLCAT_CH_DECEL_BURBLE)
        
        # SFX Layer channels
        self.channel_startup = pygame.mixer.Channel(HELLCAT_CH_STARTUP)
        self.channel_shift_sfx = pygame.mixer.Channel(HELLCAT_CH_SHIFT_SFX)
        
        # State tracking
        self.idle_target_volume = HELLCAT_NORMAL_IDLE_VOLUME
        self.idle_current_volume = HELLCAT_NORMAL_IDLE_VOLUME
        self.idle_is_fading = False
        
        # Whine crossfading state
        self.whine_low_active_channel = self.channel_whine_low_a
        self.whine_low_crossfading = False
        self.whine_low_crossfade_start_time = 0
        
        self.whine_high_active_channel = self.channel_whine_high_a
        self.whine_high_crossfading = False
        self.whine_high_crossfade_start_time = 0
        
        # Audio fade tracking
        self.accel_response_fade_start = 0
        self.accel_response_fading = False
        
        # NEW: Audio inertia system - current volumes chase target volumes
        self.rumble_low_current_vol = 0.0
        self.rumble_low_target_vol = 0.0
        self.rumble_mid_current_vol = 0.0  
        self.rumble_mid_target_vol = 0.0
        self.whine_low_current_vol = 0.0
        self.whine_low_target_vol = 0.0
        self.whine_high_current_vol = 0.0
        self.whine_high_target_vol = 0.0
        
        # NEW: Rev queue system - allows queueing up to 3 revs
        self.rev_queue = []
        self.max_rev_queue_size = 3

    def _load_sound_with_duration(self, filename):
        path = os.path.join(HELLCAT_SOUND_FILES_PATH, filename)
        if os.path.exists(path):
            try:
                sound = pygame.mixer.Sound(path)
                return sound, sound.get_length()
            except pygame.error as e:
                print(f"Hellcat Warning: Could not load '{filename}': {e}")
                return None, 0
        print(f"Hellcat Warning: Sound file not found '{filename}' at '{path}'")
        return None, 0

    def load_sounds(self):
        # Foundation Layer sounds
        self.sounds['idle'], _ = self._load_sound_with_duration("hellcat_idle_loop.wav")
        self.sounds['rumble_low'], _ = self._load_sound_with_duration("hellcat_rumble_low_rpm_loop.wav")
        self.sounds['rumble_mid'], _ = self._load_sound_with_duration("hellcat_rumble_mid_rpm_loop.wav")
        self.sounds['whine_low'], _ = self._load_sound_with_duration("hellcat_whine_low_rpm_loop.wav")
        self.sounds['whine_high'], _ = self._load_sound_with_duration("hellcat_whine_high_rpm_loop.wav")
        
        # Character Layer sounds
        self.sounds['exhaust_roar'], _ = self._load_sound_with_duration("hellcat_exhaust_roar.wav")
        self.sounds['decel_burble'], _ = self._load_sound_with_duration("hellcat_decel_burble.wav")
        
        # SFX Layer sounds
        self.sounds['startup'], _ = self._load_sound_with_duration("hellcat_startup_roar.wav")
        self.sounds['upshift'], _ = self._load_sound_with_duration("hellcat_upshift_bark.wav")
        self.sounds['downshift_1'], _ = self._load_sound_with_duration("hellcat_downshift_revmatch1.wav")
        self.sounds['downshift_2'], _ = self._load_sound_with_duration("hellcat_downshift_revmatch2.wav")
        
        # Rev sounds (simple system)
        self.sounds['rev_1'], _ = self._load_sound_with_duration("hellcat_rev_1.wav")
        self.sounds['rev_2'], _ = self._load_sound_with_duration("hellcat_rev_2.wav")
        self.sounds['rev_3'], _ = self._load_sound_with_duration("hellcat_rev_3.wav")

    def set_idle_target_volume(self, target_volume, instant=False):
        target_volume = max(0.0, min(1.0, target_volume))
        if abs(self.idle_target_volume - target_volume) > 0.01 or instant:
            self.idle_target_volume = target_volume
            if instant:
                self.idle_current_volume = target_volume
                if self.channel_idle.get_sound():
                    self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)
                self.idle_is_fading = False
            else:
                if abs(self.idle_current_volume - self.idle_target_volume) > 0.01:
                    self.idle_is_fading = True

    def update_idle_fade(self, dt):
        if self.idle_is_fading and self.channel_idle.get_busy():
            if abs(self.idle_current_volume - self.idle_target_volume) < 0.01:
                self.idle_current_volume = self.idle_target_volume
                self.idle_is_fading = False
            elif self.idle_current_volume < self.idle_target_volume:
                self.idle_current_volume = min(self.idle_current_volume + SUPRA_IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            else:
                self.idle_current_volume = max(self.idle_current_volume - SUPRA_IDLE_TRANSITION_SPEED * dt, self.idle_target_volume)
            
            if self.channel_idle.get_sound():
                self.channel_idle.set_volume(self.idle_current_volume * MASTER_ENGINE_VOL)

    def _power_curve(self, input_val, power=2.2):
        """Apply power curve for more natural volume transitions"""
        return pow(max(0.0, min(1.0, input_val)), power)
    
    def _equal_power_crossfade(self, progress):
        """Equal-power crossfade curve for smooth layer transitions"""
        import math
        fade_out = math.cos(progress * math.pi / 2)
        fade_in = math.sin(progress * math.pi / 2) 
        return fade_out, fade_in
    
    def _update_audio_inertia(self, dt):
        """Update all audio inertia - volumes chase their targets smoothly"""
        # Rumble low inertia
        if abs(self.rumble_low_current_vol - self.rumble_low_target_vol) > 0.01:
            if self.rumble_low_current_vol < self.rumble_low_target_vol:
                self.rumble_low_current_vol = min(
                    self.rumble_low_current_vol + HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.rumble_low_target_vol
                )
            else:
                self.rumble_low_current_vol = max(
                    self.rumble_low_current_vol - HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.rumble_low_target_vol
                )
        
        # Rumble mid inertia
        if abs(self.rumble_mid_current_vol - self.rumble_mid_target_vol) > 0.01:
            if self.rumble_mid_current_vol < self.rumble_mid_target_vol:
                self.rumble_mid_current_vol = min(
                    self.rumble_mid_current_vol + HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.rumble_mid_target_vol
                )
            else:
                self.rumble_mid_current_vol = max(
                    self.rumble_mid_current_vol - HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.rumble_mid_target_vol
                )
        
        # Whine low inertia
        if abs(self.whine_low_current_vol - self.whine_low_target_vol) > 0.01:
            if self.whine_low_current_vol < self.whine_low_target_vol:
                self.whine_low_current_vol = min(
                    self.whine_low_current_vol + HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.whine_low_target_vol
                )
            else:
                self.whine_low_current_vol = max(
                    self.whine_low_current_vol - HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.whine_low_target_vol
                )
        
        # Whine high inertia
        if abs(self.whine_high_current_vol - self.whine_high_target_vol) > 0.01:
            if self.whine_high_current_vol < self.whine_high_target_vol:
                self.whine_high_current_vol = min(
                    self.whine_high_current_vol + HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.whine_high_target_vol
                )
            else:
                self.whine_high_current_vol = max(
                    self.whine_high_current_vol - HELLCAT_AUDIO_INERTIA_SPEED * dt,
                    self.whine_high_target_vol
                )

    def play_foundation_layer(self, smoothed_throttle, simulated_rpm):
        """ENHANCED: Play foundation layer with audio inertia and power curves"""
        # Idle sound (unchanged - works well)
        idle_sound = self.sounds.get('idle')
        if idle_sound:
            if not self.channel_idle.get_busy() or self.channel_idle.get_sound() != idle_sound:
                self.channel_idle.play(idle_sound, loops=-1)
            
            if smoothed_throttle <= HELLCAT_THROTTLE_IDLE_THRESHOLD:
                idle_volume = 1.0
            else:
                idle_volume = max(0.0, 1.0 - (smoothed_throttle - HELLCAT_THROTTLE_IDLE_THRESHOLD) / 0.1)
            
            self.channel_idle.set_volume(idle_volume * self.idle_current_volume * MASTER_ENGINE_VOL)
        
        # ENHANCED: Rumble system with audio inertia and equal-power crossfading
        rumble_low = self.sounds.get('rumble_low')
        rumble_mid = self.sounds.get('rumble_mid')
        
        if smoothed_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD:
            # Calculate crossfade progress between rumble layers
            # Low rumble dominates 0-60% throttle, Mid rumble dominates 40-100% throttle
            crossfade_start = 0.4
            crossfade_end = 0.6
            
            if smoothed_throttle < crossfade_start:
                # Pure low rumble
                low_progress = (smoothed_throttle - HELLCAT_THROTTLE_IDLE_THRESHOLD) / (crossfade_start - HELLCAT_THROTTLE_IDLE_THRESHOLD)
                self.rumble_low_target_vol = self._power_curve(low_progress, 1.8)
                self.rumble_mid_target_vol = 0.0
            elif smoothed_throttle > crossfade_end:
                # Pure mid rumble  
                mid_progress = (smoothed_throttle - crossfade_end) / (1.0 - crossfade_end)
                self.rumble_low_target_vol = 0.0
                self.rumble_mid_target_vol = self._power_curve(mid_progress, 2.5)
            else:
                # Crossfade zone - equal power crossfade
                fade_progress = (smoothed_throttle - crossfade_start) / (crossfade_end - crossfade_start)
                fade_out, fade_in = self._equal_power_crossfade(fade_progress)
                base_progress = (smoothed_throttle - HELLCAT_THROTTLE_IDLE_THRESHOLD) / (1.0 - HELLCAT_THROTTLE_IDLE_THRESHOLD)
                base_vol = self._power_curve(base_progress, 2.0)
                
                self.rumble_low_target_vol = base_vol * fade_out
                self.rumble_mid_target_vol = base_vol * fade_in
            
            # Start/manage rumble channels
            if rumble_low and self.rumble_low_target_vol > 0.01:
                if not self.channel_rumble_low.get_busy():
                    self.channel_rumble_low.play(rumble_low, loops=-1)
                self.channel_rumble_low.set_volume(self.rumble_low_current_vol * MASTER_ENGINE_VOL)
            else:
                self.channel_rumble_low.stop()
                
            if rumble_mid and self.rumble_mid_target_vol > 0.01:
                if not self.channel_rumble_mid.get_busy():
                    self.channel_rumble_mid.play(rumble_mid, loops=-1) 
                self.channel_rumble_mid.set_volume(self.rumble_mid_current_vol * MASTER_ENGINE_VOL)
            else:
                self.channel_rumble_mid.stop()
        else:
            # Idle - fade out targets
            self.rumble_low_target_vol = 0.0
            self.rumble_mid_target_vol = 0.0
            if self.rumble_low_current_vol < 0.01:
                self.channel_rumble_low.stop()
            if self.rumble_mid_current_vol < 0.01:
                self.channel_rumble_mid.stop()
        
        # ENHANCED: Supercharger whine with power curves and inertia
        self._update_whine_sounds_enhanced(smoothed_throttle, simulated_rpm)
    
    def _update_whine_sounds_enhanced(self, smoothed_throttle, simulated_rpm):
        """ENHANCED: Supercharger whine with audio inertia and power curves"""
        whine_low = self.sounds.get('whine_low')
        whine_high = self.sounds.get('whine_high')
        
        if smoothed_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD:
            # Enhanced whine volume calculation with power curves and RPM influence
            base_intensity = self._power_curve(smoothed_throttle, 1.6)
            rpm_factor = min(1.0, (simulated_rpm - HELLCAT_IDLE_RPM) / (HELLCAT_REDLINE_RPM - HELLCAT_IDLE_RPM))
            rpm_boost = 0.3 * self._power_curve(rpm_factor, 1.2)
            
            # Low RPM whine - stronger at lower throttle, fades as high whine takes over
            if whine_low:
                low_throttle_factor = max(0.0, 1.0 - (smoothed_throttle - 0.3) / 0.4)  # Fades 30-70%
                self.whine_low_target_vol = (base_intensity + rpm_boost) * low_throttle_factor * 0.8
                
                self._manage_whine_crossfade('low', whine_low, smoothed_throttle)
                self.whine_low_active_channel.set_volume(self.whine_low_current_vol * MASTER_ENGINE_VOL)
            
            # High RPM whine - starts at 40% throttle, dominates at high throttle  
            if whine_high and smoothed_throttle > 0.4:
                high_progress = (smoothed_throttle - 0.4) / 0.6
                high_intensity = self._power_curve(high_progress, 2.0)
                self.whine_high_target_vol = (high_intensity + rpm_boost) * 1.0
                
                self._manage_whine_crossfade('high', whine_high, smoothed_throttle)
                self.whine_high_active_channel.set_volume(self.whine_high_current_vol * MASTER_ENGINE_VOL)
            else:
                self.whine_high_target_vol = 0.0
                if self.whine_high_current_vol < 0.01:
                    self.channel_whine_high_a.stop()
                    self.channel_whine_high_b.stop()
        else:
            # Idle - fade out targets
            self.whine_low_target_vol = 0.0
            self.whine_high_target_vol = 0.0
            if self.whine_low_current_vol < 0.01:
                self.channel_whine_low_a.stop()
                self.channel_whine_low_b.stop()
            if self.whine_high_current_vol < 0.01:
                self.channel_whine_high_a.stop()
                self.channel_whine_high_b.stop()

    def _update_whine_sounds(self, smoothed_throttle, simulated_rpm):
        """Handle supercharger whine with two-channel crossfading"""
        whine_low = self.sounds.get('whine_low')
        whine_high = self.sounds.get('whine_high')
        
        if smoothed_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD:
            # Low RPM whine
            if whine_low:
                self._manage_whine_crossfade('low', whine_low, smoothed_throttle)
                
                # Volume and pitch increase with RPM
                whine_volume = min(0.8, smoothed_throttle * 1.2)
                pitch_factor = 1.0 + (simulated_rpm - HELLCAT_IDLE_RPM) / 3000.0
                
                self.whine_low_active_channel.set_volume(whine_volume * MASTER_ENGINE_VOL)
            
            # High RPM whine (starts at higher throttle)
            if whine_high and smoothed_throttle > 0.4:
                self._manage_whine_crossfade('high', whine_high, smoothed_throttle)
                
                high_volume = min(1.0, (smoothed_throttle - 0.4) * 1.5)
                self.whine_high_active_channel.set_volume(high_volume * MASTER_ENGINE_VOL)
            else:
                self.channel_whine_high_a.stop()
                self.channel_whine_high_b.stop()
        else:
            # Stop all whine sounds when at idle
            self.channel_whine_low_a.stop()
            self.channel_whine_low_b.stop()
            self.channel_whine_high_a.stop()
            self.channel_whine_high_b.stop()

    def _manage_whine_crossfade(self, whine_type, sound, smoothed_throttle):
        """Manage two-channel crossfading for whine sounds"""
        current_time = time.time()
        
        if whine_type == 'low':
            active_channel = self.whine_low_active_channel
            crossfading = self.whine_low_crossfading
            crossfade_start = self.whine_low_crossfade_start_time
            channel_a = self.channel_whine_low_a
            channel_b = self.channel_whine_low_b
        else:
            active_channel = self.whine_high_active_channel
            crossfading = self.whine_high_crossfading
            crossfade_start = self.whine_high_crossfade_start_time
            channel_a = self.channel_whine_high_a
            channel_b = self.channel_whine_high_b
        
        # Start playing if not already playing
        if not active_channel.get_busy():
            active_channel.play(sound, loops=-1)
        
        # Check if we need to start crossfading (near end of clip)
        if not crossfading and active_channel.get_busy():
            # For 14-second whine_low, start crossfade at 13.5 seconds
            # For shorter clips, start at 85% through
            sound_length = sound.get_length() if hasattr(sound, 'get_length') else 14.0
            crossfade_trigger = sound_length - 0.5
            
            # Estimate current position (rough approximation)
            play_time = current_time - getattr(self, f'whine_{whine_type}_play_start', current_time)
            
            if play_time >= crossfade_trigger:
                # Start crossfade
                inactive_channel = channel_b if active_channel == channel_a else channel_a
                inactive_channel.set_volume(0)
                inactive_channel.play(sound, loops=-1)
                
                if whine_type == 'low':
                    self.whine_low_crossfading = True
                    self.whine_low_crossfade_start_time = current_time
                else:
                    self.whine_high_crossfading = True
                    self.whine_high_crossfade_start_time = current_time
        
        # Update crossfade if active
        if crossfading:
            elapsed_ms = (current_time - crossfade_start) * 1000
            progress = min(1.0, elapsed_ms / HELLCAT_CROSSFADE_DURATION)
            
            if whine_type == 'low':
                inactive_channel = self.channel_whine_low_b if active_channel == self.channel_whine_low_a else self.channel_whine_low_a
            else:
                inactive_channel = self.channel_whine_high_b if active_channel == self.channel_whine_high_a else self.channel_whine_high_a
            
            # Crossfade volumes
            if inactive_channel.get_busy():
                inactive_channel.set_volume(progress * MASTER_ENGINE_VOL)
            
            if progress >= 1.0:
                # Crossfade complete
                active_channel.stop()
                if whine_type == 'low':
                    self.whine_low_active_channel = inactive_channel
                    self.whine_low_crossfading = False
                    self.whine_low_play_start = current_time
                else:
                    self.whine_high_active_channel = inactive_channel
                    self.whine_high_crossfading = False
                    self.whine_high_play_start = current_time

    def play_character_layer(self, engine_load, simulated_rpm, smoothed_throttle):
        """Handle acceleration/deceleration response sounds"""
        current_time = time.time()
        
        # Acceleration response
        if engine_load > 0.05:  # Throttle being applied
            exhaust_roar = self.sounds.get('exhaust_roar')
            if exhaust_roar and not self.channel_accel_response.get_busy():
                volume = min(1.0, engine_load * 2)
                self.channel_accel_response.set_volume(volume * MASTER_ENGINE_VOL)
                self.channel_accel_response.play(exhaust_roar)
                
                self.accel_response_fading = True
                self.accel_response_fade_start = current_time
        
        # Deceleration burble
        if engine_load < -0.05:  # Throttle being released
            decel_burble = self.sounds.get('decel_burble')
            if decel_burble:
                if not self.channel_decel_burble.get_busy():
                    volume = min(0.8, abs(engine_load) * 1.5)
                    rpm_factor = min(1.0, simulated_rpm / 3000.0)
                    self.channel_decel_burble.set_volume(volume * rpm_factor * MASTER_ENGINE_VOL)
                    self.channel_decel_burble.play(decel_burble, loops=-1)
        else:
            if self.channel_decel_burble.get_busy():
                self.channel_decel_burble.fadeout(200)

    def play_startup_sound(self):
        """Play engine startup sound"""
        startup_sound = self.sounds.get('startup')
        if startup_sound:
            self.channel_startup.stop()
            self.channel_startup.set_volume(MASTER_ENGINE_VOL)
            self.channel_startup.play(startup_sound)
            return True
        return False

    def play_upshift_sound(self):
        """Play upshift sound"""
        upshift_sound = self.sounds.get('upshift')
        if upshift_sound:
            self.channel_shift_sfx.stop()
            self.channel_shift_sfx.set_volume(MASTER_ENGINE_VOL)
            self.channel_shift_sfx.play(upshift_sound)
            return True
        return False

    def play_downshift_sound(self):
        """Play randomly selected downshift sound"""
        downshift_sounds = ['downshift_1', 'downshift_2']
        selected_sound_key = random.choice(downshift_sounds)
        downshift_sound = self.sounds.get(selected_sound_key)
        
        if downshift_sound:
            self.channel_shift_sfx.stop()
            self.channel_shift_sfx.set_volume(MASTER_ENGINE_VOL)
            self.channel_shift_sfx.play(downshift_sound)
            print(f"Hellcat playing: {selected_sound_key}")
            return True
        return False

    def is_startup_busy(self):
        return self.channel_startup.get_busy()

    def is_shift_busy(self):
        return self.channel_shift_sfx.get_busy()
    
    def play_simple_rev(self):
        """Queue a rev sound or play immediately if not busy"""
        rev_sounds = ['rev_1', 'rev_2', 'rev_3']
        selected_sound_key = random.choice(rev_sounds)
        
        if not self.channel_shift_sfx.get_busy():
            # Channel is free, play immediately
            return self._play_rev_now(selected_sound_key)
        else:
            # Channel is busy, add to queue if not full
            if len(self.rev_queue) < self.max_rev_queue_size:
                self.rev_queue.append(selected_sound_key)
                print(f"Hellcat rev queued: {selected_sound_key} (queue: {len(self.rev_queue)}/3)")
                return True
            else:
                print(f"Hellcat rev queue full, dropping: {selected_sound_key}")
                return False
    
    def _play_rev_now(self, sound_key):
        """Play a rev sound immediately"""
        rev_sound = self.sounds.get(sound_key)
        if rev_sound:
            self.channel_shift_sfx.stop()
            self.channel_shift_sfx.set_volume(MASTER_ENGINE_VOL)
            self.channel_shift_sfx.play(rev_sound)
            print(f"Hellcat rev playing: {sound_key}")
            return True
        return False
    
    def _process_rev_queue(self):
        """Process queued rev sounds when channel becomes free"""
        if not self.channel_shift_sfx.get_busy() and self.rev_queue:
            next_rev = self.rev_queue.pop(0)  # Remove first item from queue
            self._play_rev_now(next_rev)
            if self.rev_queue:
                print(f"Hellcat rev queue remaining: {len(self.rev_queue)}")
            else:
                print("Hellcat rev queue empty")
    
    def is_rev_busy(self):
        """Check if a rev sound is playing (shares shift channel)"""
        return self.channel_shift_sfx.get_busy()

    def update(self, dt):
        """ENHANCED: Update fades and audio inertia system"""
        self.update_idle_fade(dt)
        
        # Process queued rev sounds
        self._process_rev_queue()
        
        # NEW: Update audio inertia - volumes chase targets smoothly
        self._update_audio_inertia(dt)
        
        # Update accel response fade
        if self.accel_response_fading and self.channel_accel_response.get_busy():
            current_time = time.time()
            fade_duration = HELLCAT_FADE_OUT_DURATION / 1000.0
            elapsed = current_time - self.accel_response_fade_start
            
            if elapsed >= fade_duration:
                self.accel_response_fading = False
            else:
                # Natural fade out
                fade_progress = elapsed / fade_duration
                if fade_progress > 0.5:  # Start fading after halfway point
                    fade_vol = max(0.0, 1.0 - ((fade_progress - 0.5) * 2))
                    current_vol = self.channel_accel_response.get_volume()
                    self.channel_accel_response.set_volume(current_vol * fade_vol)

    def stop_all_sounds(self):
        """Stop all sounds"""
        self.channel_idle.stop()
        self.channel_rumble_low.stop()
        self.channel_rumble_mid.stop()
        self.channel_whine_low_a.stop()
        self.channel_whine_low_b.stop()
        self.channel_whine_high_a.stop()
        self.channel_whine_high_b.stop()
        self.channel_accel_response.stop()
        self.channel_decel_burble.stop()
        self.channel_startup.stop()
        self.channel_shift_sfx.stop()
        
        self.idle_is_fading = False
        self.whine_low_crossfading = False
        self.whine_high_crossfading = False
        self.accel_response_fading = False

    def fade_out_all_sounds(self, fade_ms):
        """Fade out all sounds"""
        if self.channel_idle.get_busy():
            self.channel_idle.fadeout(fade_ms)
        if self.channel_rumble_low.get_busy():
            self.channel_rumble_low.fadeout(fade_ms)
        if self.channel_rumble_mid.get_busy():
            self.channel_rumble_mid.fadeout(fade_ms)
        if self.channel_whine_low_a.get_busy():
            self.channel_whine_low_a.fadeout(fade_ms)
        if self.channel_whine_low_b.get_busy():
            self.channel_whine_low_b.fadeout(fade_ms)
        if self.channel_whine_high_a.get_busy():
            self.channel_whine_high_a.fadeout(fade_ms)
        if self.channel_whine_high_b.get_busy():
            self.channel_whine_high_b.fadeout(fade_ms)
        if self.channel_accel_response.get_busy():
            self.channel_accel_response.fadeout(fade_ms)
        if self.channel_decel_burble.get_busy():
            self.channel_decel_burble.fadeout(fade_ms)
        if self.channel_startup.get_busy():
            self.channel_startup.fadeout(fade_ms)
        if self.channel_shift_sfx.get_busy():
            self.channel_shift_sfx.fadeout(fade_ms)
        
        # Clear rev queue when fading out all sounds
        self.clear_rev_queue()
    
    def clear_rev_queue(self):
        """Clear all queued revs"""
        if self.rev_queue:
            print(f"Hellcat clearing {len(self.rev_queue)} queued revs")
            self.rev_queue.clear()

class M4EngineSimulation:
    def __init__(self, sound_manager):
        self.sm = sound_manager
        self.state = "ENGINE_OFF" 
        self.current_throttle = 0.0
        self.throttle_history = collections.deque(maxlen=M4_GESTURE_MAX_POINTS)
        self.peak_throttle_in_gesture = 0.0
        self.gesture_start_time = 0.0
        self.in_potential_gesture = False
        
        self.gesture_lockout_until_time = 0.0

        self.time_at_100_throttle = 0.0
        self.time_in_idle = 0.0
        self.played_full_accel_sequence_recently = False
        self.time_in_launch_control_range = 0.0

        self.simulated_rpm = M4_RPM_IDLE
        self.last_rev_sound_finish_time = 0.0

    def update(self, dt, new_throttle_value):
        previous_throttle_this_frame = self.current_throttle
        self.current_throttle = new_throttle_value
        current_time = time.time()

        self.throttle_history.append((current_time, self.current_throttle))

        self.sm.update_long_sequence_crossfade()
        self.sm.update_idle_fade(dt)
        self.sm.update() # SoundManager internal state updates, including LC logic

        is_rev_sound_playing = self.sm.channel_staged_rev and self.sm.channel_staged_rev.get_busy()
        
        if not is_rev_sound_playing and current_time > self.last_rev_sound_finish_time + M4_RPM_DECAY_COOLDOWN_AFTER_REV :
            if self.simulated_rpm > M4_RPM_IDLE:
                self.simulated_rpm = max(M4_RPM_IDLE, self.simulated_rpm - M4_RPM_DECAY_RATE_PER_SEC * dt)
        
        if not is_rev_sound_playing and \
           current_time > self.last_rev_sound_finish_time + M4_RPM_RESET_TO_IDLE_THRESHOLD_TIME:
            self.simulated_rpm = M4_RPM_IDLE

        if self.state == "ENGINE_OFF":
            if self.current_throttle > THROTTLE_DEADZONE_LOW + 0.05:
                print("\nM4 Engine Starting Triggered...")
                self.state = "STARTING"
                self.sm.play_starter_sfx()
                self.current_throttle = 0.0 
                self.throttle_history.append((current_time, self.current_throttle))
                self.simulated_rpm = M4_RPM_IDLE 
                self.last_rev_sound_finish_time = current_time 

        elif self.state == "STARTING":
            if not self.sm.is_turbo_limiter_sfx_busy() and not self.sm.is_launch_control_active():
                print("\nM4 Engine Idling.")
                self.state = "IDLING"
                self.sm.set_idle_target_volume(M4_NORMAL_IDLE_VOLUME)
                self.sm.play_idle()
                self.time_in_idle = 0.0
                self.simulated_rpm = M4_RPM_IDLE
                self.last_rev_sound_finish_time = current_time

        elif self.state == "IDLING" or self.state == "PLAYFUL_REV":
            if self.state == "IDLING":
                self.time_in_idle += dt
                if self.time_in_idle > M4_FULL_ACCEL_RESET_IDLE_TIME:
                    self.played_full_accel_sequence_recently = False
                if not self.sm.any_playful_sfx_active() and not self.sm.is_launch_control_active():
                     self.sm.set_idle_target_volume(M4_NORMAL_IDLE_VOLUME)
            else: 
                self.sm.set_idle_target_volume(M4_LOW_IDLE_VOLUME_DURING_SFX) 
                if not self.sm.any_playful_sfx_active(): 
                    self.state = "IDLING"
                    self.time_in_idle = 0.0 
                    self.sm.set_idle_target_volume(M4_NORMAL_IDLE_VOLUME)

            is_in_lc_throttle_range = (M4_LAUNCH_CONTROL_THROTTLE_MIN < self.current_throttle < M4_LAUNCH_CONTROL_THROTTLE_MAX)
            
            if is_in_lc_throttle_range and (not M4_LAUNCH_CONTROL_BRAKE_REQUIRED) and self.state != "LAUNCH_HOLD":
                self.time_in_launch_control_range += dt
                if self.time_in_launch_control_range >= M4_LAUNCH_CONTROL_HOLD_DURATION and not self.sm.is_launch_control_active():
                    print("\nM4 Launch Control Engaged!")
                    self.state = "LAUNCH_HOLD"
                    self.sm.stop_staged_rev_sound() 
                    self.sm.stop_turbo_limiter_sfx()
                    if self.sm.play_launch_control_sequence():
                         self.sm.set_idle_target_volume(M4_VERY_LOW_IDLE_VOLUME_DURING_LAUNCH, instant=True)
                    else:
                        self.state = "IDLING"
                    self.time_in_launch_control_range = 0.0
                    self.time_at_100_throttle = 0.0
                    self.simulated_rpm = M4_RPM_IDLE 
                    self.last_rev_sound_finish_time = current_time
                    return 
            elif not is_in_lc_throttle_range and self.state != "LAUNCH_HOLD":
                self.time_in_launch_control_range = 0.0

            if self.state != "LAUNCH_HOLD":
                self._check_playful_gestures(current_time, previous_throttle_this_frame)

            if self.current_throttle >= 0.98:
                self.time_at_100_throttle += dt
                if self.time_at_100_throttle >= M4_SUSTAINED_100_THROTTLE_TIME and \
                   not self.played_full_accel_sequence_recently and \
                   self.state not in ["ACCELERATING", "LAUNCH_HOLD"]:
                    print("\nM4 Full Acceleration!")
                    self.state = "ACCELERATING"
                    self.sm.set_idle_target_volume(0.0, instant=True)
                    self.sm.stop_launch_control_sequence(fade_ms=50)
                    self.sm.stop_staged_rev_sound() 
                    self.sm.stop_turbo_limiter_sfx()
                    self.sm.play_long_sequence('accel_gears', start_offset=M4_ACCELERATION_SOUND_OFFSET)
                    self.played_full_accel_sequence_recently = True
                    self.time_at_100_throttle = 0.0
                    self.simulated_rpm = M4_RPM_IDLE 
                    self.last_rev_sound_finish_time = current_time
            else:
                self.time_at_100_throttle = 0.0

        elif self.state == "LAUNCH_HOLD":
            self.sm.set_idle_target_volume(M4_VERY_LOW_IDLE_VOLUME_DURING_LAUNCH, instant=True)
            
            # --- FIX #1: Corrected Launch Hold Exit Logic ---
            if self.current_throttle >= 0.98:
                # This is a LAUNCH - go directly to ACCELERATING
                print("\nM4 Launching!")
                self.state = "ACCELERATING"
                self.sm.stop_launch_control_sequence(fade_ms=0) 
                self.sm.set_idle_target_volume(0.0, instant=True)
                self.sm.play_long_sequence('accel_gears', start_offset=M4_ACCELERATION_SOUND_OFFSET)
                self.played_full_accel_sequence_recently = True
                self.simulated_rpm = M4_RPM_IDLE 
                self.last_rev_sound_finish_time = current_time
            elif not (M4_LAUNCH_CONTROL_THROTTLE_MIN < self.current_throttle < M4_LAUNCH_CONTROL_THROTTLE_MAX) or \
                 not self.sm.is_launch_control_active():
                # This is a DISENGAGE (by letting go of throttle) - only go to IDLING if throttle is low
                if self.sm.is_launch_control_active():
                    print("\nM4 Launch Control Disengaged.")
                self.state = "IDLING"
                self.sm.stop_launch_control_sequence()
                self.sm.set_idle_target_volume(M4_NORMAL_IDLE_VOLUME)
                if self.sm.sounds.get('idle'): self.sm.play_idle()
                self.time_in_idle = 0.0
                self.simulated_rpm = M4_RPM_IDLE
                self.last_rev_sound_finish_time = current_time

        elif self.state == "ACCELERATING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            if self.current_throttle < 0.90:
                if self.state != "DECELERATING": print("\nM4 Decelerating...")
                self.state = "DECELERATING"
                # FIX: Use stop-then-play instead of crossfade to prevent audio overload
                self.sm.stop_long_sequence(fade_ms=100)  # Quick fade out
                time.sleep(0.05)  # Brief pause to let fade complete
                self.sm.play_long_sequence('decel_downshifts', transition_from_other=False)
            elif not self.sm.is_long_sequence_busy() and not self.sm.transitioning_long_sound:
                if self.current_throttle >= 0.90:
                    if self.state != "CRUISING": print("\nM4 Cruising...")
                    self.state = "CRUISING"
                    # FIX: Use stop-then-play instead of crossfade to prevent audio overload
                    self.sm.stop_long_sequence(fade_ms=100)  # Quick fade out
                    time.sleep(0.05)  # Brief pause to let fade complete
                    self.sm.play_long_sequence('cruising', loops=-1, transition_from_other=False)
                else:
                    if self.state != "DECELERATING": print("\nM4 Decelerating (from accel end)...")
                    self.state = "DECELERATING"
                    # FIX: Use stop-then-play instead of crossfade to prevent audio overload
                    self.sm.stop_long_sequence(fade_ms=100)  # Quick fade out
                    time.sleep(0.05)  # Brief pause to let fade complete
                    self.sm.play_long_sequence('decel_downshifts', transition_from_other=False)

        elif self.state == "CRUISING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            if self.current_throttle < 0.90:
                if self.state != "DECELERATING": print("\nM4 Decelerating (from cruise)...")
                self.state = "DECELERATING"
                # FIX: Use stop-then-play instead of crossfade to prevent audio overload
                self.sm.stop_long_sequence(fade_ms=100)  # Quick fade out
                time.sleep(0.05)  # Brief pause to let fade complete
                self.sm.play_long_sequence('decel_downshifts', transition_from_other=False)

        elif self.state == "DECELERATING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            
            # --- FIX #2: Simplified and Corrected Re-acceleration Logic ---
            # The key is to prioritize accelerating over cruising. Any strong throttle input
            # from a coast should be considered acceleration.
            if self.current_throttle >= 0.85: # A more generous threshold to re-engage
                if self.state != "ACCELERATING": 
                    print(f"\nM4 Back to Accelerating (from decel) - throttle: {self.current_throttle:.3f}")
                self.state = "ACCELERATING"
                self.sm.stop_long_sequence(fade_ms=100)
                time.sleep(0.05)
                self.sm.play_long_sequence('accel_gears', start_offset=M4_ACCELERATION_SOUND_OFFSET, transition_from_other=False)
                self.played_full_accel_sequence_recently = True
            elif not self.sm.is_long_sequence_busy() and not self.sm.transitioning_long_sound:
                # This only runs if the throttle is LOW and the deceleration sound has finished playing.
                if self.state != "IDLING": 
                    print("\nM4 Back to Idling (from decel end).")
                self.state = "IDLING"
                self.sm.set_idle_target_volume(M4_NORMAL_IDLE_VOLUME)
                if self.sm.sounds.get('idle'): self.sm.play_idle()
                self.time_in_idle = 0.0
                self.simulated_rpm = M4_RPM_IDLE 
                self.last_rev_sound_finish_time = current_time

    def _check_playful_gestures(self, current_time, old_throttle_value_for_frame):
        if self.sm.is_long_sequence_busy() or self.state == "LAUNCH_HOLD" or self.sm.is_launch_control_active():
            self.in_potential_gesture = False
            return

        if not self.in_potential_gesture and current_time >= self.gesture_lockout_until_time:
            is_rising_from_idle = (len(self.throttle_history) < 2 or self.throttle_history[-2][1] <= THROTTLE_DEADZONE_LOW)
            if self.current_throttle > THROTTLE_DEADZONE_LOW and is_rising_from_idle:
                self.in_potential_gesture = True
                self.gesture_start_time = current_time
                self.peak_throttle_in_gesture = self.current_throttle
        
        if self.in_potential_gesture:
            self.peak_throttle_in_gesture = max(self.peak_throttle_in_gesture, self.current_throttle)

            if current_time - self.gesture_start_time > M4_GESTURE_WINDOW_TIME:
                self.in_potential_gesture = False
                return

            is_falling_after_peak = (self.current_throttle < self.peak_throttle_in_gesture * 0.7) and \
                                    (self.current_throttle < old_throttle_value_for_frame) and \
                                    (self.current_throttle <= THROTTLE_DEADZONE_LOW * 1.5)

            if is_falling_after_peak and self.peak_throttle_in_gesture > THROTTLE_DEADZONE_LOW + 0.02:
                current_gesture_peak_throttle = self.peak_throttle_in_gesture
                
                self.in_potential_gesture = False 
                self.gesture_lockout_until_time = current_time + M4_GESTURE_RETRIGGER_LOCKOUT
                rev_sound_info = self.sm.play_staged_rev(self.simulated_rpm, current_gesture_peak_throttle)
                
                if rev_sound_info:
                    self.simulated_rpm = rev_sound_info['rpm_peak']
                    self.last_rev_sound_finish_time = current_time + rev_sound_info['duration']
                    
                    self.sm.set_idle_target_volume(M4_LOW_IDLE_VOLUME_DURING_SFX) 
                    if self.state in ["IDLING", "PLAYFUL_REV"]:
                        self.state = "PLAYFUL_REV"
                    self.time_at_100_throttle = 0.0

# ENHANCED Supra Engine Simulation (from simulator)
class SupraEngineSimulation:
    def __init__(self, sound_manager):
        self.sm = sound_manager
        self.state = "ENGINE_OFF"
        
        # Raw and EMA throttle values (NEW from simulator)
        self.raw_throttle = 0.0
        self.ema_throttle = 0.0
        
        # Rev gesture detection (adapted from M4)
        self.throttle_history = collections.deque(maxlen=20)
        self.in_potential_rev_gesture = False
        self.rev_gesture_start_time = 0.0
        self.peak_throttle_in_rev_gesture = 0.0
        self.rev_gesture_lockout_until_time = 0.0
        
        # State machine tracking (NEW from simulator)
        self.state_start_time = 0.0
        
        # Audio queue system (NEW from simulator)
        self.audio_queue = None
        self.current_playing_sound_range = None
        
        # RPM simulation (NEW from simulator, adapted from M4)
        self.simulated_rpm = SUPRA_RPM_IDLE
        self.last_rev_sound_finish_time = 0.0

    def update(self, dt, new_raw_throttle):
        previous_raw_throttle = self.raw_throttle # Needed for rev gesture
        self.raw_throttle = new_raw_throttle
        
        # Update EMA throttle (NEW from simulator)
        self.ema_throttle = (SUPRA_EMA_ALPHA * self.raw_throttle) + ((1 - SUPRA_EMA_ALPHA) * self.ema_throttle)
        
        current_time = time.time()
        self.throttle_history.append((current_time, self.raw_throttle))
        self.sm.update_idle_fade(dt)
        self.sm.update_driving_crossfade()  # NEW from simulator

        # RPM simulation (NEW from simulator, adapted from M4)
        is_rev_sound_playing = self.sm.channel_rev_sfx.get_busy()
        
        if not is_rev_sound_playing and current_time > self.last_rev_sound_finish_time + SUPRA_RPM_DECAY_COOLDOWN_AFTER_REV:
            if self.simulated_rpm > SUPRA_RPM_IDLE:
                self.simulated_rpm = max(SUPRA_RPM_IDLE, self.simulated_rpm - SUPRA_RPM_DECAY_RATE_PER_SEC * dt)
        
        if not is_rev_sound_playing and \
           current_time > self.last_rev_sound_finish_time + SUPRA_RPM_RESET_TO_IDLE_THRESHOLD_TIME:
            self.simulated_rpm = SUPRA_RPM_IDLE

        # ENHANCED State machine (from simulator)
        if self.state == "ENGINE_OFF":
            if self.raw_throttle > THROTTLE_DEADZONE_LOW + 0.05:
                print("\nSupra Engine Starting...")
                self.state = "STARTING"
                self.state_start_time = current_time
                self.sm.play_startup_sound()
                self.raw_throttle = 0.0
                self.ema_throttle = 0.0
                self.simulated_rpm = SUPRA_RPM_IDLE
                self.last_rev_sound_finish_time = current_time

        elif self.state == "STARTING":
            if not self.sm.channel_rev_sfx.get_busy():
                print("\nSupra Engine Idling.")
                self.state = "IDLE"
                self.state_start_time = current_time
                self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
                self.sm.play_idle()
                self.simulated_rpm = SUPRA_RPM_IDLE
                self.last_rev_sound_finish_time = current_time

        elif self.state == "IDLE":
            self._handle_idle_state(current_time, previous_raw_throttle)

        elif self.state == "PRE_ACCEL": # NEW STATE from simulator
            self._handle_pre_accel_state(current_time)

        elif self.state == "ACCELERATING":
            self._handle_accelerating_state(current_time)

        elif self.state == "CRUISING":
            self._handle_cruising_state(current_time)

        elif self.state == "DECELERATING":
            self._handle_decelerating_state(current_time)

    # NEW: Enhanced state handlers from simulator
    def _handle_idle_state(self, current_time, previous_raw_throttle):
        """FIXED: Handle IDLE state logic with rev gesture priority"""
        if not self.sm.is_rev_sound_busy():
            self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
            if not self.sm.channel_idle.get_busy():
                self.sm.play_idle()
        
        # ALWAYS check for rev gestures first
        self._check_rev_gestures(current_time, previous_raw_throttle)
        
        # CRITICAL FIX: Don't trigger driving states if rev gesture is active or recently completed
        if self.in_potential_rev_gesture:
            # Rev gesture in progress - don't transition to driving states
            return
        
        # Also don't transition if a rev just finished (brief exclusion period)
        if current_time < (self.rev_gesture_lockout_until_time - SUPRA_REV_RETRIGGER_LOCKOUT + 0.3):
            # Rev recently completed - give it 300ms exclusion
            return
        
        ema_range = self._get_throttle_range(self.ema_throttle)
        
        # ENHANCED: Only transition to driving if throttle is sustained (not a quick blip)
        if ema_range != 'idle':
            # Additional check: make sure this isn't just EMA lag from a completed rev gesture
            # If raw throttle is back to idle but EMA is still elevated, wait for EMA to settle
            if self.raw_throttle <= THROTTLE_DEADZONE_LOW * 1.2 and self.ema_throttle > 0.08:
                # This is likely EMA lag from a rev gesture - don't transition
                return
                
            print(f"\nSupra IDLE -> PRE_ACCEL (EMA range: {ema_range}, sustained throttle)")
            self.state = "PRE_ACCEL"
            self.state_start_time = current_time
            self.sm.set_idle_target_volume(0.0)

    def _handle_pre_accel_state(self, current_time):
        """NEW: Wait for a moment to gauge user's final throttle intent."""
        time_in_state = current_time - self.state_start_time
        
        # If grace period is over, decide what to do.
        if time_in_state >= SUPRA_PRE_ACCEL_DELAY:
            ema_range = self._get_throttle_range(self.ema_throttle)
            
            if ema_range == 'idle': # User bailed and went back to idle
                self.state = "IDLE"
                self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
                return

            # Commit to accelerating with the sound for the CURRENT range
            print(f"Supra PRE_ACCEL -> ACCELERATING (Intent: {ema_range}, EMA: {self.ema_throttle:.3f})")
            self.state = "ACCELERATING"
            self.state_start_time = current_time # Reset timer for this new state
            
            if self._play_pull_sound_for_range(ema_range):
                self.current_playing_sound_range = ema_range

    def _handle_accelerating_state(self, current_time):
        """Handle ACCELERATING state with audio queue system"""
        ema_range = self._get_throttle_range(self.ema_throttle)
        
        if ema_range == 'idle':
            print("\nSupra ACCELERATING -> DECELERATING (waiting for audio to finish)")
            self.state = "DECELERATING"
            self.state_start_time = current_time
            self.audio_queue = None
            return
        
        if self.sm.is_driving_sound_busy():
            if ema_range != self.current_playing_sound_range:
                self.audio_queue = {'range': ema_range, 'sound_type': 'pull'}
        else:
            if self.audio_queue:
                queued_range = self.audio_queue['range']
                if queued_range == self._get_throttle_range(self.ema_throttle):
                    if self._play_pull_sound_for_range(queued_range):
                        self.current_playing_sound_range = queued_range
                self.audio_queue = None
            else:
                time_since_pull_ended = current_time - self.state_start_time
                if time_since_pull_ended >= SUPRA_CRUISE_TRANSITION_DELAY:
                    self.state = "CRUISING"
                    cruise_type = 'highway_cruise' if ema_range == 'highway' else 'cruise'
                    if self._play_cruise_sound_for_range(ema_range, cruise_type):
                        self.current_playing_sound_range = ema_range
                else:
                    if self._play_pull_sound_for_range(ema_range):
                        self.current_playing_sound_range = ema_range

    def _handle_cruising_state(self, current_time):
        """Handle CRUISING state logic"""
        ema_range = self._get_throttle_range(self.ema_throttle)
        
        if ema_range == 'idle':
            print("\nSupra CRUISING -> DECELERATING (waiting for audio to finish)")
            self.state = "DECELERATING"
            self.state_start_time = current_time
            return
        
        if ema_range != self.current_playing_sound_range:
            print(f"\nSupra CRUISING -> ACCELERATING (Range changed)")
            self.state = "ACCELERATING"
            self.state_start_time = current_time
            if self.sm.play_driving_sound(self.ema_throttle, force_type='pull', crossfade=True):
                self.current_playing_sound_range = ema_range
            return
        
        if not self.sm.is_driving_sound_busy():
            cruise_type = 'highway_cruise' if ema_range == 'highway' else 'cruise'
            self._play_cruise_sound_for_range(ema_range, cruise_type)

    def _handle_decelerating_state(self, current_time):
        """Handle DECELERATING state - wait for current audio to finish before returning to idle"""
        ema_range = self._get_throttle_range(self.ema_throttle)
        
        # If user accelerates again before audio finishes, go back to appropriate state
        if ema_range != 'idle':
            print(f"\nSupra DECELERATING -> ACCELERATING (throttle applied again: {ema_range})")
            self.state = "ACCELERATING"
            self.state_start_time = current_time
            if self._play_pull_sound_for_range(ema_range):
                self.current_playing_sound_range = ema_range
            return
        
        # Check if driving sounds are still playing
        if self.sm.is_driving_sound_busy():
            # Still playing, keep waiting
            return
        
        # Audio finished, now we can safely transition to IDLE
        print("\nSupra DECELERATING -> IDLE (audio finished)")
        self.state = "IDLE"
        self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
        self.current_playing_sound_range = None
        # Start playing idle sound if not already playing
        if not self.sm.channel_idle.get_busy():
            self.sm.play_idle()

    def _get_throttle_range(self, throttle):
        if throttle >= SUPRA_HIGHWAY_CRUISE_THRESHOLD: return 'highway'
        elif throttle >= 0.61: return 'violent'
        elif throttle >= 0.31: return 'aggressive'
        elif throttle >= 0.10: return 'light'
        else: return 'idle'

    def _play_pull_sound_for_range(self, range_name):
        return self.sm.play_driving_sound(self.ema_throttle, force_type='pull')

    def _play_cruise_sound_for_range(self, range_name, cruise_type):
        return self.sm.play_driving_sound(self.ema_throttle, force_type=cruise_type)

    def _check_rev_gestures(self, current_time, old_throttle_value):
        """ENHANCED: Rev gesture detection with better conflict avoidance"""
        if self.state != "IDLE":
            self.in_potential_rev_gesture = False
            return

        # Start new rev gesture detection
        if not self.in_potential_rev_gesture and current_time >= self.rev_gesture_lockout_until_time:
            is_rising_from_idle = (len(self.throttle_history) < 2 or self.throttle_history[-2][1] <= THROTTLE_DEADZONE_LOW)
            if self.raw_throttle > THROTTLE_DEADZONE_LOW and is_rising_from_idle:
                print(f"Supra rev gesture START: throttle {self.raw_throttle:.3f}")
                self.in_potential_rev_gesture = True
                self.rev_gesture_start_time = current_time
                self.peak_throttle_in_rev_gesture = self.raw_throttle

        # Process ongoing rev gesture
        if self.in_potential_rev_gesture:
            self.peak_throttle_in_rev_gesture = max(self.peak_throttle_in_rev_gesture, self.raw_throttle)
            
            # Timeout check
            if current_time - self.rev_gesture_start_time > SUPRA_REV_GESTURE_WINDOW_TIME:
                print(f"Supra rev gesture TIMEOUT (peak: {self.peak_throttle_in_rev_gesture:.3f})")
                self.in_potential_rev_gesture = False
                return
            
            # ENHANCED: More precise rev completion detection
            is_falling_after_peak = (
                self.raw_throttle < self.peak_throttle_in_rev_gesture * 0.6 and  # More aggressive drop threshold
                self.raw_throttle < old_throttle_value and                        # Actually falling
                self.raw_throttle <= THROTTLE_DEADZONE_LOW * 1.8                  # Close to idle
            )
            
            # ENHANCED: Better minimum threshold to avoid tiny blips triggering revs
            min_rev_threshold = THROTTLE_DEADZONE_LOW + 0.04  # Increased from 0.02
            
            if is_falling_after_peak and self.peak_throttle_in_rev_gesture > min_rev_threshold:
                current_gesture_peak_throttle = self.peak_throttle_in_rev_gesture
                
                print(f"Supra rev gesture COMPLETE: peak {current_gesture_peak_throttle:.3f}, current {self.raw_throttle:.3f}")
                self.in_potential_rev_gesture = False
                self.rev_gesture_lockout_until_time = current_time + SUPRA_REV_RETRIGGER_LOCKOUT
                
                # Play the rev sound
                rev_sound_info = self.sm.play_staged_rev(self.simulated_rpm, current_gesture_peak_throttle)
                
                if rev_sound_info:
                    self.simulated_rpm = rev_sound_info['rpm_peak']
                    self.last_rev_sound_finish_time = current_time + rev_sound_info['duration']
                    self.sm.set_idle_target_volume(SUPRA_LOW_IDLE_VOLUME_DURING_REV)
                    print(f"Supra rev played: {rev_sound_info['key']} (RPM: {rev_sound_info['rpm_peak']})")
            elif is_falling_after_peak:
                # Rev gesture completed but was too small - cancel it
                print(f"Supra rev gesture CANCELLED: peak {self.peak_throttle_in_rev_gesture:.3f} < threshold {min_rev_threshold:.3f}")
                self.in_potential_rev_gesture = False

class HellcatEngineSimulation:
    def __init__(self, sound_manager):
        self.sm = sound_manager
        self.state = "ENGINE_OFF"
        
        # Raw and EMA throttle values
        self.raw_throttle = 0.0
        self.smoothed_throttle = 0.0
        self.previous_throttle = 0.0
        
        # Virtual engine physics
        self.simulated_rpm = HELLCAT_IDLE_RPM
        self.simulated_gear = 1
        self.engine_load = 0.0
        
        # State tracking
        self.state_start_time = 0.0
        self.last_shift_time = 0.0
        self.min_time_between_shifts = HELLCAT_MIN_SHIFT_INTERVAL  # Use the new constant
        
        # Simple rev gesture detection
        self.in_simple_rev_gesture = False
        self.rev_gesture_start_time = 0.0
        self.rev_peak_throttle = 0.0
        self.rev_lockout_until = 0.0

    def update(self, dt, new_raw_throttle):
        self.previous_throttle = self.raw_throttle
        self.raw_throttle = new_raw_throttle
        
        # Update EMA throttle
        self.smoothed_throttle = (HELLCAT_EMA_ALPHA * self.raw_throttle) + ((1 - HELLCAT_EMA_ALPHA) * self.smoothed_throttle)
        
        # Calculate engine load (rate of throttle change)
        self.engine_load = self.raw_throttle - self.previous_throttle
        
        current_time = time.time()
        self.sm.update(dt)

        # State machine
        if self.state == "ENGINE_OFF":
            if self.raw_throttle > THROTTLE_DEADZONE_LOW + 0.05:
                print("\nHellcat Engine Starting...")
                self.state = "STARTING"
                self.state_start_time = current_time
                self.sm.play_startup_sound()
                self.raw_throttle = 0.0
                self.smoothed_throttle = 0.0
                self.simulated_rpm = HELLCAT_IDLE_RPM

        elif self.state == "STARTING":
            if not self.sm.is_startup_busy():
                print("\nHellcat Engine Idling.")
                self.state = "IDLE"
                self.state_start_time = current_time
                self.sm.set_idle_target_volume(HELLCAT_NORMAL_IDLE_VOLUME)

        elif self.state == "IDLE":
            self._handle_idle_state(current_time, dt)

        elif self.state == "DRIVING":
            self._handle_driving_state(current_time, dt)

        # Always update foundation layer when engine is running
        if self.state not in ["ENGINE_OFF", "STARTING"]:
            self.sm.play_foundation_layer(self.smoothed_throttle, self.simulated_rpm)
            self.sm.play_character_layer(self.engine_load, self.simulated_rpm, self.smoothed_throttle)

    def _handle_idle_state(self, current_time, dt):
        """ENHANCED: Handle IDLE state with simple rev gesture support"""
        self.sm.set_idle_target_volume(HELLCAT_NORMAL_IDLE_VOLUME)
        
        # FIRST: Check for simple rev gestures (priority over driving states)
        self._check_simple_rev_gestures(current_time)
        
        # SECOND: Only transition to driving if NOT in a rev gesture
        if not self.in_simple_rev_gesture and self.smoothed_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD:
            # Extra check: Make sure raw throttle is also elevated (prevents EMA lag issues like Supra had)
            if self.raw_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD:
                print(f"\nHellcat IDLE -> DRIVING (smoothed: {self.smoothed_throttle:.3f}, raw: {self.raw_throttle:.3f})")
                self.state = "DRIVING"
                self.state_start_time = current_time
        
        # Update RPM decay to idle when not driving
        if self.simulated_rpm > HELLCAT_IDLE_RPM:
            self.simulated_rpm = max(HELLCAT_IDLE_RPM, self.simulated_rpm - HELLCAT_RPM_DECAY_COAST * dt)

    def _handle_driving_state(self, current_time, dt):
        """Handle DRIVING state with virtual engine physics"""
        # Check if we should return to idle
        if self.smoothed_throttle <= HELLCAT_THROTTLE_IDLE_THRESHOLD:
            print("\nHellcat DRIVING -> IDLE")
            self.state = "IDLE"
            self.sm.set_idle_target_volume(HELLCAT_NORMAL_IDLE_VOLUME)
            return
        
        # ENHANCED: Virtual RPM physics tuned for electric scooter operation
        if self.smoothed_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD:
            # Acceleration with realistic inertia
            gear_multiplier = HELLCAT_GEAR_ACCEL_MULTIPLIERS.get(self.simulated_gear, 1.0)
            rpm_increase = HELLCAT_RPM_ACCEL_BASE * self.smoothed_throttle * gear_multiplier * dt
            self.simulated_rpm += rpm_increase
        else:
            # ENHANCED: Much more aggressive deceleration, especially on throttle lift
            gear_braking = HELLCAT_GEAR_ENGINE_BRAKING.get(self.simulated_gear, 500)
            
            # If throttle was just released (negative engine load), apply aggressive braking
            if self.engine_load < -0.05:
                total_decay = HELLCAT_RPM_THROTTLE_LIFT_DECAY + gear_braking  # Much faster
            else:
                total_decay = HELLCAT_RPM_DECAY_COAST + gear_braking  # Normal coast
            
            self.simulated_rpm = max(HELLCAT_IDLE_RPM, self.simulated_rpm - total_decay * dt)
        
        # CRITICAL: Cap RPM at redline regardless of gear (fixes infinite RPM in 5th gear)
        self.simulated_rpm = min(self.simulated_rpm, HELLCAT_REDLINE_RPM)
        
        # Handle upshifts (with timing constraint)
        time_since_last_shift = current_time - self.last_shift_time
        if (self.simulated_rpm >= HELLCAT_REDLINE_RPM and 
            self.simulated_gear < 5 and 
            time_since_last_shift >= self.min_time_between_shifts):
            
            print(f"Hellcat upshift: {self.simulated_gear} -> {self.simulated_gear + 1} at {self.simulated_rpm:.0f} RPM (time since last: {time_since_last_shift:.1f}s)")
            if self.sm.play_upshift_sound():
                self.sm.set_idle_target_volume(HELLCAT_LOW_IDLE_VOLUME_DURING_SHIFT)
            
            old_gear = self.simulated_gear
            self.simulated_gear += 1
            # Reset RPM to much lower value after upshift
            new_rpm = 1800 + (self.simulated_gear * 100)  # 1900, 2000, 2100, 2200 for gears 2,3,4,5
            print(f"RPM reset from {self.simulated_rpm:.0f} to {new_rpm:.0f}")
            self.simulated_rpm = new_rpm
            self.last_shift_time = current_time
        elif self.simulated_rpm >= HELLCAT_REDLINE_RPM and self.simulated_gear < 5:
            print(f"Upshift blocked - time constraint: {time_since_last_shift:.1f}s < {self.min_time_between_shifts}s")
        
        # ENHANCED: Downshift logic tuned for electric scooter (more responsive)
        if (self.simulated_gear > 1 and 
            current_time - self.last_shift_time >= self.min_time_between_shifts):
            
            downshift_threshold = HELLCAT_GEAR_DOWNSHIFT_THRESHOLDS.get(self.simulated_gear, 1500)
            
            # Scenario 1: IMMEDIATE throttle release downshift (electric scooter pattern)
            immediate_throttle_release = (
                self.engine_load < -0.15 and  # Significant throttle reduction
                self.simulated_rpm < downshift_threshold * 1.4  # More generous RPM range
            )
            
            # Scenario 2: RPM naturally dropped too low for current gear
            natural_rpm_downshift = (
                self.simulated_rpm < downshift_threshold and
                self.smoothed_throttle < 0.4  # More liberal threshold
            )
            
            # Scenario 3: Coming to a stop (very low RPM, very low throttle)
            stopping_downshift = (
                self.simulated_rpm < 1400 and  # Higher threshold for easier downshifting
                self.smoothed_throttle < 0.15
            )
            
            # NEW Scenario 4: Sustained low throttle after being at high throttle
            sustained_low_throttle = (
                self.smoothed_throttle < 0.1 and
                self.simulated_rpm < downshift_threshold * 1.3 and
                current_time - self.last_shift_time >= self.min_time_between_shifts * 0.7  # Shorter wait
            )
            
            if immediate_throttle_release or natural_rpm_downshift or stopping_downshift or sustained_low_throttle:
                downshift_type = "immediate" if immediate_throttle_release else "natural" if natural_rpm_downshift else "stopping" if stopping_downshift else "sustained"
                print(f"Hellcat {downshift_type} downshift: {self.simulated_gear} -> {self.simulated_gear - 1} at {self.simulated_rpm:.0f} RPM (throttle: {self.smoothed_throttle:.2f}, load: {self.engine_load:.2f})")
                
                if self.sm.play_downshift_sound():
                    self.sm.set_idle_target_volume(HELLCAT_LOW_IDLE_VOLUME_DURING_SHIFT)
                
                self.simulated_gear -= 1
                # Enhanced rev-match with more realistic blip
                rev_match_increase = 400 + (self.simulated_gear * 150)  # More realistic rev-match
                self.simulated_rpm = min(HELLCAT_REDLINE_RPM * 0.75, self.simulated_rpm + rev_match_increase)
                self.last_shift_time = current_time
        
        # Restore idle volume after shift events
        if not self.sm.is_shift_busy():
            self.sm.set_idle_target_volume(HELLCAT_NORMAL_IDLE_VOLUME)
    
    def _check_simple_rev_gestures(self, current_time):
        """SIMPLE: Rev gesture detection for Hellcat (much simpler than Supra)"""
        # Only check for revs when idling
        if self.state != "IDLE":
            self.in_simple_rev_gesture = False
            return
        
        # Start rev gesture detection
        if not self.in_simple_rev_gesture and current_time >= self.rev_lockout_until:
            # Looking for throttle rise from idle
            if (self.raw_throttle > HELLCAT_THROTTLE_IDLE_THRESHOLD * 2 and  # At least 10% throttle
                self.previous_throttle <= HELLCAT_THROTTLE_IDLE_THRESHOLD * 1.5):  # Was at idle before
                
                print(f"Hellcat simple rev START: {self.raw_throttle:.3f}")
                self.in_simple_rev_gesture = True
                self.rev_gesture_start_time = current_time
                self.rev_peak_throttle = self.raw_throttle
        
        # Process ongoing rev gesture
        if self.in_simple_rev_gesture:
            self.rev_peak_throttle = max(self.rev_peak_throttle, self.raw_throttle)
            
            # Timeout after 1 second
            if current_time - self.rev_gesture_start_time > 1.0:
                print(f"Hellcat simple rev TIMEOUT (peak: {self.rev_peak_throttle:.3f})")
                self.in_simple_rev_gesture = False
                return
            
            # Check if throttle is dropping back to idle
            is_dropping_to_idle = (
                self.raw_throttle < self.rev_peak_throttle * 0.5 and  # Dropped to half of peak
                self.raw_throttle <= HELLCAT_THROTTLE_IDLE_THRESHOLD * 2  # Back near idle
            )
            
            if is_dropping_to_idle and self.rev_peak_throttle > 0.08:  # Minimum 8% peak
                print(f"Hellcat simple rev COMPLETE: peak {self.rev_peak_throttle:.3f}")
                self.in_simple_rev_gesture = False
                self.rev_lockout_until = current_time + 0.5  # Half second lockout
                
                # Play random rev sound
                if self.sm.play_simple_rev():
                    self.sm.set_idle_target_volume(HELLCAT_LOW_IDLE_VOLUME_DURING_SHIFT)
            elif is_dropping_to_idle:
                print(f"Hellcat simple rev CANCELLED: peak {self.rev_peak_throttle:.3f} too small")
                self.in_simple_rev_gesture = False

class TripleCarSystem:
    def __init__(self):
        self.m4_sound_manager = M4SoundManager()
        self.supra_sound_manager = SupraSoundManager()
        self.hellcat_sound_manager = HellcatSoundManager()
        self.m4_engine = M4EngineSimulation(self.m4_sound_manager)
        self.supra_engine = SupraEngineSimulation(self.supra_sound_manager)
        self.hellcat_engine = HellcatEngineSimulation(self.hellcat_sound_manager)
        
        self.cars = ["M4", "Supra", "Hellcat"]
        self.current_car_index = 0
        self.current_car = self.cars[self.current_car_index]
        self.switching_cars = False
        self.switch_start_time = 0
        
        self.throttle_buffer = collections.deque(maxlen=THROTTLE_SMOOTHING_WINDOW_SIZE)
        for _ in range(THROTTLE_SMOOTHING_WINDOW_SIZE):
            self.throttle_buffer.append(0.0)

    def switch_car(self):
        if self.switching_cars:
            return
        
        # Cycle to next car
        self.current_car_index = (self.current_car_index + 1) % len(self.cars)
        new_car = self.cars[self.current_car_index]
        old_car = self.current_car
        
        print(f"\nSwitching from {old_car} to {new_car}...")
        self.switching_cars = True
        self.switch_start_time = time.time()
        
        # Fade out current car's sounds
        if old_car == "M4":
            self.m4_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)
        elif old_car == "Supra":
            self.supra_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)
        else:  # Hellcat
            self.hellcat_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)

    def update(self, dt, raw_throttle):
        self.throttle_buffer.append(raw_throttle)
        smoothed_throttle = sum(self.throttle_buffer) / len(self.throttle_buffer)
        
        current_time = time.time()

        # Handle car switching
        if self.switching_cars:
            if current_time - self.switch_start_time >= (SUPRA_CROSSFADE_DURATION_MS / 1000.0):
                # Switch is complete
                if self.current_car == "M4":
                    self.m4_sound_manager.stop_all_sounds()
                elif self.current_car == "Supra":
                    self.supra_sound_manager.stop_all_sounds()
                else:  # Hellcat
                    self.hellcat_sound_manager.stop_all_sounds()
                
                # Switch to new car
                self.current_car = self.cars[self.current_car_index]
                
                # Reset new car's engine state
                if self.current_car == "M4":
                    self.m4_engine.state = "ENGINE_OFF"
                elif self.current_car == "Supra":
                    self.supra_engine.state = "ENGINE_OFF"
                else:  # Hellcat
                    self.hellcat_engine.state = "ENGINE_OFF"
                    self.hellcat_engine.simulated_rpm = HELLCAT_IDLE_RPM
                    self.hellcat_engine.simulated_gear = 1
                    self.hellcat_engine.last_shift_time = 0.0
                
                print(f"Switched to {self.current_car}")
                self.switching_cars = False
            else:
                return smoothed_throttle, raw_throttle

        # Update the active car's engine
        if self.current_car == "M4":
            self.m4_engine.update(dt, smoothed_throttle)
        elif self.current_car == "Supra":
            self.supra_engine.update(dt, raw_throttle)  # Pass raw throttle to Supra for gestures
        else:  # Hellcat
            self.hellcat_engine.update(dt, raw_throttle)  # Pass raw throttle to Hellcat for physics
        
        return smoothed_throttle, raw_throttle

    def get_active_engine(self):
        if self.current_car == "M4":
            return self.m4_engine
        elif self.current_car == "Supra":
            return self.supra_engine
        else:  # Hellcat
            return self.hellcat_engine

    def get_active_sound_manager(self):
        if self.current_car == "M4":
            return self.m4_sound_manager
        elif self.current_car == "Supra":
            return self.supra_sound_manager
        else:  # Hellcat
            return self.hellcat_sound_manager

def handle_button():
    global button_pressed_time, last_button_state, running_script
    
    if not RASPI_HW_AVAILABLE:
        return False
    
    try:
        current_button_state = not GPIO.input(BUTTON_GPIO_PIN)  # Inverted because pull-up
        current_time = time.time()
        
        # Button press detected
        if current_button_state and not last_button_state:
            button_pressed_time = current_time
        
        # Button release detected
        elif not current_button_state and last_button_state and button_pressed_time is not None:
            press_duration = current_time - button_pressed_time
            
            if press_duration >= BUTTON_LONG_PRESS_TIME:
                print("\nLong button press detected - shutting down...")
                running_script = False
            elif press_duration >= BUTTON_DEBOUNCE_TIME:
                print("\nShort button press detected - switching cars...")
                button_pressed_time = None
                last_button_state = current_button_state
                return True  # Signal to switch cars
            
            button_pressed_time = None
        
        last_button_state = current_button_state
        
    except Exception as e:
        print(f"Button handling error: {e}")
    
    return False

def signal_handler_main(sig, frame):
    global running_script
    if running_script:
        print("\nInterrupt received. Shutting down...")
        running_script = False

def update_display(triple_car_system, current_throttle_smoothed, raw_throttle_pct, raw_adc):
    active_engine = triple_car_system.get_active_engine()
    active_sm = triple_car_system.get_active_sound_manager()
    car_name = triple_car_system.current_car
    
    # Get car-specific information
    if car_name == "M4":
        sim_rpm = getattr(active_engine, 'simulated_rpm', 0)
        extra_info = f"SimRPM: {sim_rpm:<4.0f}"
        if hasattr(active_engine, 'time_in_launch_control_range'):
            lc_time = active_engine.time_in_launch_control_range
            lc_active = active_sm.is_launch_control_active()
            extra_info += f" | LC_T: {lc_time:>4.2f}s | LC: {str(lc_active):<5}"
    elif car_name == "Supra":
        # ENHANCED: Better Supra display info from simulator
        sim_rpm = getattr(active_engine, 'simulated_rpm', 0)
        ema_throttle = getattr(active_engine, 'ema_throttle', 0)
        throttle_range = active_engine._get_throttle_range(ema_throttle) if hasattr(active_engine, '_get_throttle_range') else 'N/A'
        extra_info = f"SimRPM: {sim_rpm:<4.0f} | EMA: {ema_throttle:.3f} | Range: {throttle_range:<9}"
    else:  # Hellcat
        sim_rpm = getattr(active_engine, 'simulated_rpm', 0)
        sim_gear = getattr(active_engine, 'simulated_gear', 1)
        engine_load = getattr(active_engine, 'engine_load', 0)
        smoothed_throttle = getattr(active_engine, 'smoothed_throttle', 0)
        extra_info = f"SimRPM: {sim_rpm:<4.0f} | Gear: {sim_gear} | Load: {engine_load:>5.2f} | EMA: {smoothed_throttle:.3f}"
    
    status_string = (
        f"Car: {car_name:<5} | State: {active_engine.state:<15} | RawThr: {raw_throttle_pct:>4.2f} | "
        f"SmoothThr: {current_throttle_smoothed:>4.2f} | ADC: {raw_adc:<5} | "
        f"IdleVol: {active_sm.idle_current_volume:>4.2f} | {extra_info} | Switching: {triple_car_system.switching_cars}"
    )
    print(f"\r{status_string:<200}", end='', flush=True)

def main():
    global running_script, adc_throttle_channel, log_data, current_car
    signal.signal(signal.SIGINT, signal_handler_main)
    signal.signal(signal.SIGTERM, signal_handler_main)

    pygame.init()
    
    actual_channels = 0
    min_channels_needed = 10 
    mixer_initialized_ok = False

    try:
        pygame.mixer.init(frequency=MIXER_FREQUENCY, size=MIXER_SIZE, channels=MIXER_CHANNELS_STEREO, buffer=MIXER_BUFFER)
        if pygame.mixer.get_init():
            pygame.mixer.set_num_channels(NUM_PYGAME_MIXER_CHANNELS)
            actual_channels = pygame.mixer.get_num_channels()
            print(f"Pygame Mixer initialized. Requested {NUM_PYGAME_MIXER_CHANNELS}, Got {actual_channels} channels.")
            mixer_initialized_ok = True
        else:
            print("Pygame Mixer failed to initialize with custom settings.")
    except pygame.error as e:
        print(f"Error initializing Pygame mixer with custom settings: {e}.")

    if not mixer_initialized_ok:
        print("Attempting Pygame Mixer default initialization...")
        try:
            pygame.mixer.init()
            if pygame.mixer.get_init():
                pygame.mixer.set_num_channels(NUM_PYGAME_MIXER_CHANNELS)
                actual_channels = pygame.mixer.get_num_channels()
                print(f"Pygame Mixer fallback initialization succeeded. Requested {NUM_PYGAME_MIXER_CHANNELS}, Got {actual_channels} channels.")
                mixer_initialized_ok = True
            else:
                print("CRITICAL ERROR: Pygame Mixer failed to initialize even with default settings.")
                actual_channels = 0
        except pygame.error as e_fallback:
            print(f"CRITICAL ERROR: Pygame Mixer fallback initialization also failed: {e_fallback}.")
            actual_channels = 0

    if mixer_initialized_ok and actual_channels < min_channels_needed:
        print(f"CRITICAL WARNING: Mixer has {actual_channels} channels, but at least {min_channels_needed} are recommended. Sound issues may occur.")
    elif not mixer_initialized_ok:
         print("Mixer initialization ultimately failed. SoundManager might not create channels correctly.")

    if not RASPI_HW_AVAILABLE:
        print("--- RUNNING IN SIMULATED ADC MODE (NO RASPBERRY PI HARDWARE) ---")
    else:
        if not initialize_adc():
            print("--- FAILED TO INITIALIZE ADC. SIMULATING 0% THROTTLE ---")
        if not initialize_button():
            print("--- BUTTON DISABLED ---")
        else:
            print("--- RUNNING WITH RASPBERRY PI ADC HARDWARE ---")

    os.makedirs(M4_SOUND_FILES_PATH, exist_ok=True)
    os.makedirs(SUPRA_SOUND_FILES_PATH, exist_ok=True)

    # Check for essential M4 sound files
    m4_sound_files_to_check = [
        "engine_idle_loop.wav", 
        "engine_rev_stage1.wav", "engine_rev_stage2.wav", "engine_rev_stage3.wav", "engine_rev_stage4.wav",
        "launch_control_engage.wav", "launch_control_hold_loop.wav", "acceleration_gears_1_to_4.wav"
    ]
    missing_files = False
    for sf in m4_sound_files_to_check:
        if not os.path.exists(os.path.join(M4_SOUND_FILES_PATH, sf)):
            print(f"Warning: Essential M4 sound file '{sf}' not found in '{M4_SOUND_FILES_PATH}/'. Please add it.")
            missing_files = True

    # Check for essential Supra sound files (ENHANCED from simulator)
    supra_sound_files_to_check = [
        "supra_idle_loop.wav", "supra_startup.wav",
        "light_pull_1.wav", "aggressive_push_1.wav", "violent_pull_1.wav",
        "supra_rev_stage1.wav", "supra_rev_stage2.wav", "supra_rev_stage3.wav", "supra_rev_stage4.wav"
    ]
    for sf in supra_sound_files_to_check:
        if not os.path.exists(os.path.join(SUPRA_SOUND_FILES_PATH, sf)):
            print(f"Warning: Essential Supra sound file '{sf}' not found in '{SUPRA_SOUND_FILES_PATH}/'. Please add it.")
            missing_files = True

    # Check for essential Hellcat sound files
    hellcat_sound_files_to_check = [
        "hellcat_idle_loop.wav", "hellcat_startup_roar.wav",
        "hellcat_rumble_low_rpm_loop.wav", "hellcat_rumble_mid_rpm_loop.wav",
        "hellcat_whine_low_rpm_loop.wav", "hellcat_whine_high_rpm_loop.wav",
        "hellcat_exhaust_roar.wav", "hellcat_decel_burble.wav",
        "hellcat_upshift_bark.wav", "hellcat_downshift_revmatch1.wav", "hellcat_downshift_revmatch2.wav",
        "hellcat_rev_1.wav", "hellcat_rev_2.wav", "hellcat_rev_3.wav"  # Simple rev system
    ]
    for sf in hellcat_sound_files_to_check:
        if not os.path.exists(os.path.join(HELLCAT_SOUND_FILES_PATH, sf)):
            print(f"Warning: Essential Hellcat sound file '{sf}' not found in '{HELLCAT_SOUND_FILES_PATH}/'. Please add it.")
            missing_files = True

    if missing_files:
        print("--- Some essential sound files are missing. Functionality will be significantly affected. ---")

    triple_car_system = TripleCarSystem()
    
    print("\nTriple Car EV Sound Simulation Running (Headless)...")
    print(f"Starting car: {triple_car_system.current_car}")
    print(f"Throttle smoothing window: {THROTTLE_SMOOTHING_WINDOW_SIZE} samples")
    print(f"M4 - Staged Rev System Active. Simulating RPM: Idle {M4_RPM_IDLE}, Decay {M4_RPM_DECAY_RATE_PER_SEC}/s")
    print(f"M4 - Gesture Retrigger Lockout: {M4_GESTURE_RETRIGGER_LOCKOUT}s")
    print(f"M4 - Launch Control: Hold throttle {M4_LAUNCH_CONTROL_THROTTLE_MIN*100:.0f}%-"
          f"{M4_LAUNCH_CONTROL_THROTTLE_MAX*100:.0f}% for {M4_LAUNCH_CONTROL_HOLD_DURATION}s")
    print(f"Supra - ENHANCED Engine with EMA Throttle (α={SUPRA_EMA_ALPHA}) and PRE_ACCEL State")
    print(f"Supra - Staged Rev System Active. Simulating RPM: Idle {SUPRA_RPM_IDLE}, Decay {SUPRA_RPM_DECAY_RATE_PER_SEC}/s")
    print(f"Supra - Rev Gesture Lockout: {SUPRA_REV_RETRIGGER_LOCKOUT}s | Pre-Accel Delay: {SUPRA_PRE_ACCEL_DELAY}s")
    print(f"Hellcat - Virtual Engine with EMA Throttle (α={HELLCAT_EMA_ALPHA}) and Automatic Transmission")
    print(f"Hellcat - RPM Simulation: Idle {HELLCAT_IDLE_RPM}, Redline {HELLCAT_REDLINE_RPM}, 5-Speed Auto")
    print(f"Hellcat - Foundation Layer: Idle + Rumble + Supercharger Whine with Crossfading")
    print(f"Throttle Input: ADC P{ADC_CHANNEL_NUMBER} -> {MIN_ADC_VALUE} (0%) to {MAX_ADC_VALUE} (100%)")
    print(f"Button: GPIO {BUTTON_GPIO_PIN} (short press = switch car, long press = shutdown)")
    print(f"Log file will be: {LOG_FILE_NAME}")
    print("Press Ctrl+C to exit gracefully.\n")

    last_time = time.time()
    last_display_update_time = time.time()

    try:
        while running_script:
            current_time_loop = time.time()
            dt = current_time_loop - last_time
            if dt <= 0: dt = 1/FPS # Should be a very small positive number
            last_time = current_time_loop

            # Handle button
            if handle_button():
                triple_car_system.switch_car()

            raw_adc = read_adc_value()
            raw_throttle_percentage = get_throttle_percentage_from_adc(raw_adc)
            
            smoothed_throttle_percentage, _ = triple_car_system.update(dt, raw_throttle_percentage)
            
            active_engine = triple_car_system.get_active_engine()
            active_sm = triple_car_system.get_active_sound_manager()

            log_entry = {
                "timestamp_unix": current_time_loop, "datetime_iso": datetime.datetime.now().isoformat(), "dt": dt,
                "active_car": triple_car_system.current_car, "switching_cars": triple_car_system.switching_cars,
                "state": active_engine.state, "raw_adc": raw_adc,
                "raw_throttle_input_pct": raw_throttle_percentage, "smoothed_throttle_pct": smoothed_throttle_percentage,
                "engine_current_throttle_pct": getattr(active_engine, 'current_throttle', getattr(active_engine, 'raw_throttle', 0)),
                "idle_target_vol": active_sm.idle_target_volume, "idle_current_vol": active_sm.idle_current_volume,
                "idle_is_fading": active_sm.idle_is_fading, "idle_chan_busy": active_sm.channel_idle.get_busy(),
            }

            # Add car-specific logging
            if triple_car_system.current_car == "M4":
                log_entry.update({
                    "m4_sim_rpm": active_engine.simulated_rpm, 
                    "m4_last_rev_finish_t": active_engine.last_rev_sound_finish_time,
                    "m4_staged_rev_chan_busy": active_sm.channel_staged_rev.get_busy() if active_sm.channel_staged_rev else False,
                    "m4_staged_rev_chan_sound": active_sm.get_sound_name_from_obj(active_sm.channel_staged_rev.get_sound() if active_sm.channel_staged_rev else None),
                    "m4_sfx_chan_busy": active_sm.channel_turbo_limiter_sfx.get_busy(),
                    "m4_sfx_chan_sound": active_sm.get_sound_name_from_obj(active_sm.channel_turbo_limiter_sfx.get_sound()),
                    "m4_lc_sounds_active": active_sm.launch_control_sounds_active,
                    "m4_waiting_for_lc_hold": active_sm.waiting_for_launch_hold_loop,
                    "m4_is_lc_active_overall": active_sm.is_launch_control_active(),
                    "m4_just_switched_lc_hold": active_sm.just_switched_to_lc_hold,
                    "m4_long_A_busy": active_sm.channel_long_A.get_busy(),
                    "m4_long_A_sound": active_sm.get_sound_name_from_obj(active_sm.channel_long_A.get_sound()),
                    "m4_long_B_busy": active_sm.channel_long_B.get_busy(),
                    "m4_long_B_sound": active_sm.get_sound_name_from_obj(active_sm.channel_long_B.get_sound()),
                    "m4_long_transitioning": active_sm.transitioning_long_sound,
                    "m4_time_@100thr": active_engine.time_at_100_throttle, 
                    "m4_time_in_idle": active_engine.time_in_idle,
                    "m4_played_accel_rec": active_engine.played_full_accel_sequence_recently,
                    "m4_time_in_lc_range": active_engine.time_in_launch_control_range,
                    "m4_in_pot_gesture": active_engine.in_potential_gesture, 
                    "m4_peak_thr_gesture": active_engine.peak_throttle_in_gesture,
                    "m4_gesture_lockout_until": active_engine.gesture_lockout_until_time
                })
            elif triple_car_system.current_car == "Supra":
                log_entry.update({
                    "supra_sim_rpm": active_engine.simulated_rpm,
                    "supra_last_rev_finish_t": active_engine.last_rev_sound_finish_time,
                    "supra_raw_throttle": active_engine.raw_throttle,
                    "supra_ema_throttle": active_engine.ema_throttle,
                    "supra_throttle_range": active_engine._get_throttle_range(active_engine.ema_throttle),
                    "supra_driving_A_busy": active_sm.channel_driving_A.get_busy(),
                    "supra_driving_A_sound": active_sm.get_sound_name_from_obj(active_sm.channel_driving_A.get_sound()),
                    "supra_driving_B_busy": active_sm.channel_driving_B.get_busy(),
                    "supra_driving_B_sound": active_sm.get_sound_name_from_obj(active_sm.channel_driving_B.get_sound()),
                    "supra_rev_sfx_busy": active_sm.channel_rev_sfx.get_busy(),
                    "supra_rev_sfx_sound": active_sm.get_sound_name_from_obj(active_sm.channel_rev_sfx.get_sound()),
                    "supra_in_pot_rev_gesture": active_engine.in_potential_rev_gesture,
                    "supra_peak_thr_rev_gesture": active_engine.peak_throttle_in_rev_gesture,
                    "supra_rev_gesture_lockout_until": active_engine.rev_gesture_lockout_until_time,
                    "supra_audio_queue": str(active_engine.audio_queue),
                    "supra_current_playing_sound_range": active_engine.current_playing_sound_range,
                    "supra_last_clip_start": active_sm.last_clip_start_time,
                    "supra_transitioning_driving": active_sm.transitioning_driving_sound
                })
            else:  # Hellcat
                log_entry.update({
                    "hellcat_sim_rpm": active_engine.simulated_rpm,
                    "hellcat_sim_gear": active_engine.simulated_gear,
                    "hellcat_raw_throttle": active_engine.raw_throttle,
                    "hellcat_smoothed_throttle": active_engine.smoothed_throttle,
                    "hellcat_engine_load": active_engine.engine_load,
                    "hellcat_last_shift_time": active_engine.last_shift_time,
                    "hellcat_idle_busy": active_sm.channel_idle.get_busy(),
                    "hellcat_rumble_low_busy": active_sm.channel_rumble_low.get_busy(),
                    "hellcat_rumble_mid_busy": active_sm.channel_rumble_mid.get_busy(),
                    "hellcat_whine_low_a_busy": active_sm.channel_whine_low_a.get_busy(),
                    "hellcat_whine_low_b_busy": active_sm.channel_whine_low_b.get_busy(),
                    "hellcat_whine_high_a_busy": active_sm.channel_whine_high_a.get_busy(),
                    "hellcat_whine_high_b_busy": active_sm.channel_whine_high_b.get_busy(),
                    "hellcat_accel_response_busy": active_sm.channel_accel_response.get_busy(),
                    "hellcat_decel_burble_busy": active_sm.channel_decel_burble.get_busy(),
                    "hellcat_startup_busy": active_sm.channel_startup.get_busy(),
                    "hellcat_shift_sfx_busy": active_sm.channel_shift_sfx.get_busy(),
                    "hellcat_whine_low_crossfading": active_sm.whine_low_crossfading,
                    "hellcat_whine_high_crossfading": active_sm.whine_high_crossfading,
                    "hellcat_accel_response_fading": active_sm.accel_response_fading
                })

            log_data.append(log_entry)

            if current_time_loop - last_display_update_time >= DISPLAY_UPDATE_INTERVAL:
                update_display(
                    triple_car_system, smoothed_throttle_percentage, 
                    raw_throttle_percentage, raw_adc
                )
                last_display_update_time = current_time_loop

            processing_time = time.time() - current_time_loop
            sleep_duration = max(0, (1.0 / FPS) - processing_time)
            time.sleep(sleep_duration)

    except Exception as e:
        print(f"\r{' ' * 200}\r", end='', flush=True) # Clear the line
        print(f"\nUNEXPECTED ERROR in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\r{' ' * 200}\r", end='', flush=True) # Clear the line
        print("\nInitiating final cleanup...")
        
        if log_data:
            print(f"Writing log data to {LOG_FILE_NAME}...")
            try:
                field_names = set()
                for entry in log_data: field_names.update(entry.keys())
                
                preferred_order = [
                    "timestamp_unix", "datetime_iso", "dt", "active_car", "switching_cars", "state", "raw_adc",
                    "raw_throttle_input_pct", "smoothed_throttle_pct", "engine_current_throttle_pct",
                    "idle_target_vol", "idle_current_vol", "idle_is_fading", "idle_chan_busy"
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

        if 'triple_car_system' in locals() and triple_car_system and pygame.mixer.get_init():
            print("Stopping all sounds...")
            triple_car_system.m4_sound_manager.stop_all_sounds()
            triple_car_system.supra_sound_manager.stop_all_sounds()
            triple_car_system.hellcat_sound_manager.stop_all_sounds()
            time.sleep(0.2) 
        
        if RASPI_HW_AVAILABLE:
            try:
                GPIO.cleanup()
                print("GPIO cleanup completed.")
            except:
                pass
        
        if pygame.mixer.get_init(): pygame.mixer.quit()
        if pygame.get_init(): pygame.quit()
        print("Shutdown complete.")

if __name__ == '__main__':
    main() 
