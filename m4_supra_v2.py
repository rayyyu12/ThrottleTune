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
NUM_PYGAME_MIXER_CHANNELS = 20 # Increased for dual car system

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
MASTER_ENGINE_VOL = 0.02 # Overall engine sound volume
M4_STAGED_REV_VOLUME = 0.9 # Volume for new staged revs relative to master
M4_LAUNCH_CONTROL_THROTTLE_MIN = 0.55
M4_LAUNCH_CONTROL_THROTTLE_MAX = 0.85
M4_LAUNCH_CONTROL_HOLD_DURATION = 0.5
M4_LAUNCH_CONTROL_BRAKE_REQUIRED = False
M4_LAUNCH_CONTROL_ENGAGE_VOL = 1.0
M4_LAUNCH_CONTROL_HOLD_VOL = 1.0
M4_GESTURE_RETRIGGER_LOCKOUT = 0.3 # Min time after any gesture (incl. new revs) before new one

# --- M4 Moving Average Parameters ---
M4_RPM_IDLE = 800
M4_RPM_DECAY_RATE_PER_SEC = 1500  # How fast RPM drops when not revving
M4_RPM_DECAY_COOLDOWN_AFTER_REV = 0.1 # Seconds after rev sound finishes before RPM starts decaying
M4_RPM_RESET_TO_IDLE_THRESHOLD_TIME = 6.0 # Seconds of inactivity after a rev to fully reset RPM to idle for next base

# Supra specific parameters
SUPRA_NORMAL_IDLE_VOLUME = 0.7  # Match M4 volume level
SUPRA_LOW_IDLE_VOLUME_DURING_REV = 0.2
SUPRA_REV_GESTURE_WINDOW_TIME = 0.75
SUPRA_REV_RETRIGGER_LOCKOUT = 0.5
SUPRA_CLIP_OVERLAP_PREVENTION_TIME = 0.3  # Minimum time between clip starts
SUPRA_CROSSFADE_DURATION_MS = 800
SUPRA_IDLE_TRANSITION_SPEED = 2.5

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

# Sound file paths
M4_SOUND_FILES_PATH = "m4"
SUPRA_SOUND_FILES_PATH = "supra"

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
            return {'rpm_peak': selected_stage_info['rpm_peak'], 'duration': selected_stage_info['duration']}
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
    
    def play_long_sequence(self, sound_key, loops=0, transition_from_other=False):
        sound_info = self.sounds.get(sound_key)
        if not sound_info : 
            print(f"M4 Long sequence sound key '{sound_key}' not found or not a direct sound object.")
            other_channel = self.channel_long_B if self.active_long_channel == self.channel_long_A else self.channel_long_A
            other_channel.stop()
            self.active_long_channel.stop()
            self.transitioning_long_sound = False
            return

        sound_to_play = sound_info 

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
        # Core sounds
        self.sounds['idle'], _ = self._load_sound_with_duration("supra_idle_loop.wav")
        self.sounds['startup'], _ = self._load_sound_with_duration("supra_startup.wav")
        
        # Light pulls and cruising sounds (10-30% throttle)
        self.sounds['light_pull_1'], _ = self._load_sound_with_duration("light_pull_1.wav")
        self.sounds['light_pull_2'], _ = self._load_sound_with_duration("light_pull_2.wav")
        self.sounds['light_cruise_1'], _ = self._load_sound_with_duration("light_cruise_1.wav")
        self.sounds['light_cruise_2'], _ = self._load_sound_with_duration("light_cruise_2.wav")
        self.sounds['light_cruise_3'], _ = self._load_sound_with_duration("light_cruise_3.wav")
        
        # Aggressive pushes (31-60% throttle)
        self.sounds['aggressive_push_1'], _ = self._load_sound_with_duration("aggressive_push_1.wav")
        self.sounds['aggressive_push_2'], _ = self._load_sound_with_duration("aggressive_push_2.wav")
        self.sounds['aggressive_push_3'], _ = self._load_sound_with_duration("aggressive_push_3.wav")
        self.sounds['aggressive_push_4'], _ = self._load_sound_with_duration("aggressive_push_4.wav")
        self.sounds['aggressive_push_5'], _ = self._load_sound_with_duration("aggressive_push_5.wav")
        self.sounds['aggressive_push_6'], _ = self._load_sound_with_duration("aggressive_push_6.wav")
        
        # Violent pulls (61-100% throttle)
        self.sounds['violent_pull_1'], _ = self._load_sound_with_duration("violent_pull_1.wav")
        self.sounds['violent_pull_2'], _ = self._load_sound_with_duration("violent_pull_2.wav")
        self.sounds['violent_pull_3'], _ = self._load_sound_with_duration("violent_pull_3.wav")
        
        # Highway cruise
        self.sounds['highway_cruise_loop'], _ = self._load_sound_with_duration("highway_cruise_loop.wav")
        
        # Rev sounds (stationary revs)
        self.sounds['rev_1'], _ = self._load_sound_with_duration("supra_rev_1.wav")
        self.sounds['rev_2'], _ = self._load_sound_with_duration("supra_rev_2.wav")
        self.sounds['rev_3'], _ = self._load_sound_with_duration("supra_rev_3.wav")

    def get_sound_name_from_obj(self, sound_obj):
        if sound_obj is None:
            return "None"
        for name, sound in self.sounds.items():
            if isinstance(sound, pygame.mixer.Sound) and sound == sound_obj:
                return name
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

    def play_driving_sound(self, throttle_percentage):
        current_time = time.time()
        
        # Prevent overlapping clips
        if current_time - self.last_clip_start_time < SUPRA_CLIP_OVERLAP_PREVENTION_TIME:
            return False
        
        # Don't interrupt currently playing clips
        if self.channel_driving_A.get_busy() or self.channel_driving_B.get_busy():
            return False
        
        selected_sound = None
        sound_name = ""
        
        # Select sound based on throttle range
        if 0.10 <= throttle_percentage <= 0.30:  # Light pulls and cruising
            light_sounds = ['light_pull_1', 'light_pull_2', 'light_cruise_1', 'light_cruise_2', 'light_cruise_3']
            available_sounds = [s for s in light_sounds if self.sounds.get(s)]
            if available_sounds:
                sound_name = random.choice(available_sounds)
                selected_sound = self.sounds[sound_name]
        
        elif 0.31 <= throttle_percentage <= 0.60:  # Aggressive pushes
            aggressive_sounds = ['aggressive_push_1', 'aggressive_push_2', 'aggressive_push_3', 
                               'aggressive_push_4', 'aggressive_push_5', 'aggressive_push_6']
            available_sounds = [s for s in aggressive_sounds if self.sounds.get(s)]
            if available_sounds:
                sound_name = random.choice(available_sounds)
                selected_sound = self.sounds[sound_name]
        
        elif 0.61 <= throttle_percentage <= 1.0:  # Violent pulls
            violent_sounds = ['violent_pull_1', 'violent_pull_2', 'violent_pull_3']
            available_sounds = [s for s in violent_sounds if self.sounds.get(s)]
            if available_sounds:
                sound_name = random.choice(available_sounds)
                selected_sound = self.sounds[sound_name]
        
        if selected_sound:
            print(f"Supra playing: {sound_name} (throttle: {throttle_percentage:.2f})")
            # Use the inactive channel for crossfading
            target_channel = self.channel_driving_B if self.active_driving_channel == self.channel_driving_A else self.channel_driving_A
            target_channel.set_volume(MASTER_ENGINE_VOL)
            target_channel.play(selected_sound)
            self.active_driving_channel = target_channel
            self.last_clip_start_time = current_time
            return True
        
        return False

    def play_rev_sound(self, peak_throttle):
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

    def is_driving_sound_busy(self):
        return self.channel_driving_A.get_busy() or self.channel_driving_B.get_busy()

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

    def fade_out_all_sounds(self, fade_ms):
        if self.channel_idle.get_busy():
            self.channel_idle.fadeout(fade_ms)
        if self.channel_driving_A.get_busy():
            self.channel_driving_A.fadeout(fade_ms)
        if self.channel_driving_B.get_busy():
            self.channel_driving_B.fadeout(fade_ms)
        if self.channel_rev_sfx.get_busy():
            self.channel_rev_sfx.fadeout(fade_ms)

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
                    self.sm.play_long_sequence('accel_gears')
                    self.played_full_accel_sequence_recently = True
                    self.time_at_100_throttle = 0.0
                    self.simulated_rpm = M4_RPM_IDLE 
                    self.last_rev_sound_finish_time = current_time
            else:
                self.time_at_100_throttle = 0.0

        elif self.state == "LAUNCH_HOLD":
            self.sm.set_idle_target_volume(M4_VERY_LOW_IDLE_VOLUME_DURING_LAUNCH, instant=True)
            if self.current_throttle >= 0.98:
                print("\nM4 Launching!")
                self.state = "ACCELERATING"
                self.sm.stop_launch_control_sequence(fade_ms=0) 
                self.sm.set_idle_target_volume(0.0, instant=True)
                self.sm.play_long_sequence('accel_gears')
                self.played_full_accel_sequence_recently = True
                self.simulated_rpm = M4_RPM_IDLE 
                self.last_rev_sound_finish_time = current_time
            elif not (M4_LAUNCH_CONTROL_THROTTLE_MIN < self.current_throttle < M4_LAUNCH_CONTROL_THROTTLE_MAX) or \
                 not self.sm.is_launch_control_active():
                if self.sm.is_launch_control_active(): # Check before stopping sounds
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
                self.sm.play_long_sequence('decel_downshifts', transition_from_other=True)
            elif not self.sm.is_long_sequence_busy() and not self.sm.transitioning_long_sound:
                if self.current_throttle >= 0.90:
                    if self.state != "CRUISING": print("\nM4 Cruising...")
                    self.state = "CRUISING"
                    self.sm.play_long_sequence('cruising', loops=-1, transition_from_other=True)
                else:
                    if self.state != "DECELERATING": print("\nM4 Decelerating (from accel end)...")
                    self.state = "DECELERATING"
                    self.sm.play_long_sequence('decel_downshifts', transition_from_other=True)

        elif self.state == "CRUISING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            if self.current_throttle < 0.90:
                if self.state != "DECELERATING": print("\nM4 Decelerating (from cruise)...")
                self.state = "DECELERATING"
                self.sm.play_long_sequence('decel_downshifts', transition_from_other=True)

        elif self.state == "DECELERATING":
            self.sm.set_idle_target_volume(0.0, instant=True)
            if self.current_throttle >= 0.95 and not self.sm.transitioning_long_sound:
                if self.state != "CRUISING": print("\nM4 Back to Cruising (from decel)...")
                self.state = "CRUISING"
                self.sm.play_long_sequence('cruising', loops=-1, transition_from_other=True)
                self.played_full_accel_sequence_recently = True
            elif not self.sm.is_long_sequence_busy() and not self.sm.transitioning_long_sound:
                if self.state != "IDLING": print("\nM4 Back to Idling (from decel end).")
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

class SupraEngineSimulation:
    def __init__(self, sound_manager):
        self.sm = sound_manager
        self.state = "ENGINE_OFF"
        self.current_throttle = 0.0
        self.throttle_history = collections.deque(maxlen=20)
        
        # Rev gesture detection
        self.in_potential_rev_gesture = False
        self.rev_gesture_start_time = 0.0
        self.peak_throttle_in_rev_gesture = 0.0
        self.rev_gesture_lockout_until_time = 0.0
        
        # Driving clip management
        self.waiting_for_clip_to_finish = False
        self.last_throttle_when_clip_started = 0.0

    def update(self, dt, new_throttle_value):
        previous_throttle = self.current_throttle
        self.current_throttle = new_throttle_value
        current_time = time.time()
        
        self.throttle_history.append((current_time, self.current_throttle))
        self.sm.update_idle_fade(dt)
        
        # CRITICAL FIX: Restore idle volume when rev sounds finish
        if self.state == "IDLE" and not self.sm.is_rev_sound_busy():
            if abs(self.sm.idle_target_volume - SUPRA_NORMAL_IDLE_VOLUME) > 0.01:
                print("Supra restoring idle volume to normal")
                self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)

        if self.state == "ENGINE_OFF":
            if self.current_throttle > THROTTLE_DEADZONE_LOW + 0.05:
                print("\nSupra Engine Starting...")
                self.state = "STARTING"
                self.sm.play_startup_sound()
                self.current_throttle = 0.0

        elif self.state == "STARTING":
            if not self.sm.channel_rev_sfx.get_busy():
                print("\nSupra Engine Idling.")
                self.state = "IDLE"
                self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
                self.sm.play_idle()

        elif self.state == "IDLE":
            self._check_rev_gestures(current_time, previous_throttle)
            
            # Check if we should play a driving sound
            if self.current_throttle >= 0.10 and not self.sm.is_driving_sound_busy():
                if self.sm.play_driving_sound(self.current_throttle):
                    self.state = "DRIVING"
                    self.waiting_for_clip_to_finish = False
                    self.last_throttle_when_clip_started = self.current_throttle
                    self.sm.set_idle_target_volume(0.0)  # Fade out idle

        elif self.state == "DRIVING":
            # If no driving sound is playing, we're done with the clip
            if not self.sm.is_driving_sound_busy():
                self.state = "ENDING_CLIP"
                self.waiting_for_clip_to_finish = False

        elif self.state == "ENDING_CLIP":
            # Smart let-off logic - decide next state based on current throttle
            if self.current_throttle < 0.05:
                # Back to idle
                print("\nSupra transitioning to idle")
                self.state = "IDLE"
                self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
                self.sm.play_idle()
            elif 0.05 <= self.current_throttle <= 0.15:
                # Light cruise
                light_cruise_sounds = ['light_cruise_1', 'light_cruise_2', 'light_cruise_3']
                available_sounds = [s for s in light_cruise_sounds if self.sm.sounds.get(s)]
                if available_sounds:
                    sound_name = random.choice(available_sounds)
                    selected_sound = self.sm.sounds[sound_name]
                    print(f"Supra transitioning to light cruise: {sound_name}")
                    self.sm.active_driving_channel.set_volume(MASTER_ENGINE_VOL)
                    self.sm.active_driving_channel.play(selected_sound)
                    self.state = "DRIVING"
                else:
                    self.state = "IDLE"
                    self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
                    self.sm.play_idle()
            elif self.current_throttle > 0.15:
                # User wants more power
                if self.sm.play_driving_sound(self.current_throttle):
                    self.state = "DRIVING"
                else:
                    self.state = "IDLE"
                    self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
                    self.sm.play_idle()

    def _check_rev_gestures(self, current_time, old_throttle_value):
        # Only allow rev gestures from idle state
        if self.state != "IDLE":
            self.in_potential_rev_gesture = False
            return

        if not self.in_potential_rev_gesture and current_time >= self.rev_gesture_lockout_until_time:
            is_rising_from_idle = (len(self.throttle_history) < 2 or self.throttle_history[-2][1] <= THROTTLE_DEADZONE_LOW)
            if self.current_throttle > THROTTLE_DEADZONE_LOW and is_rising_from_idle:
                self.in_potential_rev_gesture = True
                self.rev_gesture_start_time = current_time
                self.peak_throttle_in_rev_gesture = self.current_throttle

        if self.in_potential_rev_gesture:
            self.peak_throttle_in_rev_gesture = max(self.peak_throttle_in_rev_gesture, self.current_throttle)
            
            if current_time - self.rev_gesture_start_time > SUPRA_REV_GESTURE_WINDOW_TIME:
                self.in_potential_rev_gesture = False
                return
            
            is_falling_after_peak = (self.current_throttle < self.peak_throttle_in_rev_gesture * 0.7) and \
                                   (self.current_throttle < old_throttle_value) and \
                                   (self.current_throttle <= THROTTLE_DEADZONE_LOW * 1.5)
            
            if is_falling_after_peak and self.peak_throttle_in_rev_gesture > THROTTLE_DEADZONE_LOW + 0.02:
                self.in_potential_rev_gesture = False
                self.rev_gesture_lockout_until_time = current_time + SUPRA_REV_RETRIGGER_LOCKOUT
                
                if self.sm.play_rev_sound(self.peak_throttle_in_rev_gesture):
                    self.sm.set_idle_target_volume(SUPRA_LOW_IDLE_VOLUME_DURING_REV)

class DualCarSystem:
    def __init__(self):
        self.m4_sound_manager = M4SoundManager()
        self.supra_sound_manager = SupraSoundManager()
        self.m4_engine = M4EngineSimulation(self.m4_sound_manager)
        self.supra_engine = SupraEngineSimulation(self.supra_sound_manager)
        
        self.current_car = "M4"
        self.switching_cars = False
        self.switch_start_time = 0
        
        self.throttle_buffer = collections.deque(maxlen=THROTTLE_SMOOTHING_WINDOW_SIZE)
        for _ in range(THROTTLE_SMOOTHING_WINDOW_SIZE):
            self.throttle_buffer.append(0.0)

    def switch_car(self):
        if self.switching_cars:
            return  # Already switching
        
        new_car = "Supra" if self.current_car == "M4" else "M4"
        print(f"\nSwitching from {self.current_car} to {new_car}...")
        self.switching_cars = True
        self.switch_start_time = time.time()
        
        # Fade out current car
        if self.current_car == "M4":
            self.m4_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)
        else:
            self.supra_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)

    def update(self, dt, raw_throttle):
        # Update throttle smoothing
        self.throttle_buffer.append(raw_throttle)
        smoothed_throttle = sum(self.throttle_buffer) / len(self.throttle_buffer)
        
        current_time = time.time()
        
        # Handle car switching
        if self.switching_cars:
            if current_time - self.switch_start_time >= (SUPRA_CROSSFADE_DURATION_MS / 1000.0):
                # Switch is complete
                if self.current_car == "M4":
                    self.m4_sound_manager.stop_all_sounds()
                    self.current_car = "Supra"
                    self.supra_engine.state = "ENGINE_OFF"  # Reset engine state
                    print("Switched to Supra")
                else:
                    self.supra_sound_manager.stop_all_sounds()
                    self.current_car = "M4"
                    self.m4_engine.state = "ENGINE_OFF"  # Reset engine state
                    print("Switched to M4")
                
                self.switching_cars = False
            else:
                # During switch, don't update engines
                return smoothed_throttle, raw_throttle
        
        # Update the active car's engine
        if self.current_car == "M4":
            self.m4_engine.update(dt, smoothed_throttle)
        else:
            self.supra_engine.update(dt, smoothed_throttle)
        
        return smoothed_throttle, raw_throttle

    def get_active_engine(self):
        return self.m4_engine if self.current_car == "M4" else self.supra_engine

    def get_active_sound_manager(self):
        return self.m4_sound_manager if self.current_car == "M4" else self.supra_sound_manager

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

def update_display(dual_car_system, current_throttle_smoothed, raw_throttle_pct, raw_adc):
    active_engine = dual_car_system.get_active_engine()
    active_sm = dual_car_system.get_active_sound_manager()
    car_name = dual_car_system.current_car
    
    # Get car-specific information
    if car_name == "M4":
        sim_rpm = getattr(active_engine, 'simulated_rpm', 0)
        extra_info = f"SimRPM: {sim_rpm:<4.0f}"
        if hasattr(active_engine, 'time_in_launch_control_range'):
            lc_time = active_engine.time_in_launch_control_range
            lc_active = active_sm.is_launch_control_active()
            extra_info += f" | LC_T: {lc_time:>4.2f}s | LC: {str(lc_active):<5}"
    else:
        extra_info = f"RevBusy: {str(active_sm.is_rev_sound_busy()):<5} | DrvBusy: {str(active_sm.is_driving_sound_busy()):<5}"
    
    status_string = (
        f"Car: {car_name:<5} | State: {active_engine.state:<15} | RawThr: {raw_throttle_pct:>4.2f} | "
        f"SmoothThr: {current_throttle_smoothed:>4.2f} | ADC: {raw_adc:<5} | "
        f"IdleVol: {active_sm.idle_current_volume:>4.2f} | {extra_info} | Switching: {dual_car_system.switching_cars}"
    )
    print(f"\r{status_string:<180}", end='', flush=True)

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

    # Check for essential Supra sound files
    supra_sound_files_to_check = [
        "supra_idle_loop.wav", "supra_startup.wav",
        "light_pull_1.wav", "aggressive_push_1.wav", "violent_pull_1.wav",
        "supra_rev_1.wav", "supra_rev_2.wav", "supra_rev_3.wav"
    ]
    for sf in supra_sound_files_to_check:
        if not os.path.exists(os.path.join(SUPRA_SOUND_FILES_PATH, sf)):
            print(f"Warning: Essential Supra sound file '{sf}' not found in '{SUPRA_SOUND_FILES_PATH}/'. Please add it.")
            missing_files = True

    if missing_files:
        print("--- Some essential sound files are missing. Functionality will be significantly affected. ---")

    dual_car_system = DualCarSystem()
    
    print("\nDual Car EV Sound Simulation Running (Headless)...")
    print(f"Starting car: {dual_car_system.current_car}")
    print(f"Throttle smoothing window: {THROTTLE_SMOOTHING_WINDOW_SIZE} samples")
    print(f"M4 - Staged Rev System Active. Simulating RPM: Idle {M4_RPM_IDLE}, Decay {M4_RPM_DECAY_RATE_PER_SEC}/s")
    print(f"M4 - Gesture Retrigger Lockout: {M4_GESTURE_RETRIGGER_LOCKOUT}s")
    print(f"M4 - Launch Control: Hold throttle {M4_LAUNCH_CONTROL_THROTTLE_MIN*100:.0f}%-"
          f"{M4_LAUNCH_CONTROL_THROTTLE_MAX*100:.0f}% for {M4_LAUNCH_CONTROL_HOLD_DURATION}s")
    print(f"Supra - Simplified State Machine with Smart Let-Off Logic")
    print(f"Supra - Rev Gesture Lockout: {SUPRA_REV_RETRIGGER_LOCKOUT}s")
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
                dual_car_system.switch_car()

            raw_adc = read_adc_value()
            raw_throttle_percentage = get_throttle_percentage_from_adc(raw_adc)
            
            smoothed_throttle_percentage, _ = dual_car_system.update(dt, raw_throttle_percentage)
            
            active_engine = dual_car_system.get_active_engine()
            active_sm = dual_car_system.get_active_sound_manager()

            log_entry = {
                "timestamp_unix": current_time_loop, "datetime_iso": datetime.datetime.now().isoformat(), "dt": dt,
                "active_car": dual_car_system.current_car, "switching_cars": dual_car_system.switching_cars,
                "state": active_engine.state, "raw_adc": raw_adc,
                "raw_throttle_input_pct": raw_throttle_percentage, "smoothed_throttle_pct": smoothed_throttle_percentage,
                "engine_current_throttle_pct": active_engine.current_throttle,
                "idle_target_vol": active_sm.idle_target_volume, "idle_current_vol": active_sm.idle_current_volume,
                "idle_is_fading": active_sm.idle_is_fading, "idle_chan_busy": active_sm.channel_idle.get_busy(),
            }

            # Add car-specific logging
            if dual_car_system.current_car == "M4":
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
            else:  # Supra
                log_entry.update({
                    "supra_driving_A_busy": active_sm.channel_driving_A.get_busy(),
                    "supra_driving_A_sound": active_sm.get_sound_name_from_obj(active_sm.channel_driving_A.get_sound()),
                    "supra_driving_B_busy": active_sm.channel_driving_B.get_busy(),
                    "supra_driving_B_sound": active_sm.get_sound_name_from_obj(active_sm.channel_driving_B.get_sound()),
                    "supra_rev_sfx_busy": active_sm.channel_rev_sfx.get_busy(),
                    "supra_rev_sfx_sound": active_sm.get_sound_name_from_obj(active_sm.channel_rev_sfx.get_sound()),
                    "supra_in_pot_rev_gesture": active_engine.in_potential_rev_gesture,
                    "supra_peak_thr_rev_gesture": active_engine.peak_throttle_in_rev_gesture,
                    "supra_rev_gesture_lockout_until": active_engine.rev_gesture_lockout_until_time,
                    "supra_waiting_for_clip": active_engine.waiting_for_clip_to_finish,
                    "supra_last_clip_start": active_sm.last_clip_start_time
                })

            log_data.append(log_entry)

            if current_time_loop - last_display_update_time >= DISPLAY_UPDATE_INTERVAL:
                update_display(
                    dual_car_system, smoothed_throttle_percentage, 
                    raw_throttle_percentage, raw_adc
                )
                last_display_update_time = current_time_loop

            processing_time = time.time() - current_time_loop
            sleep_duration = max(0, (1.0 / FPS) - processing_time)
            time.sleep(sleep_duration)

    except Exception as e:
        print(f"\r{' ' * 180}\r", end='', flush=True) # Clear the line
        print(f"\nUNEXPECTED ERROR in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\r{' ' * 180}\r", end='', flush=True) # Clear the line
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

        if 'dual_car_system' in locals() and dual_car_system and pygame.mixer.get_init():
            print("Stopping all sounds...")
            dual_car_system.m4_sound_manager.stop_all_sounds()
            dual_car_system.supra_sound_manager.stop_all_sounds()
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
