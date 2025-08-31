import pygame
import tkinter as tk
from tkinter import ttk
import os
import time
import random
import collections
import threading
import csv
import datetime

# --- Constants and Parameters (adapted from Main_REV1.py) ---
FPS = 60
MIXER_FREQUENCY = 44100
MIXER_SIZE = -16
MIXER_CHANNELS_STEREO = 2
MIXER_BUFFER = 512
NUM_PYGAME_MIXER_CHANNELS = 20

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
M4_TURBO_BOV_COOLDOWN = 1.0
M4_HIGH_REV_LIMITER_COOLDOWN = 1.5
M4_FULL_ACCEL_RESET_IDLE_TIME = 3.0
M4_NORMAL_IDLE_VOLUME = 0.7
M4_LOW_IDLE_VOLUME_DURING_SFX = 0.15
M4_VERY_LOW_IDLE_VOLUME_DURING_LAUNCH = 0.05
MASTER_ENGINE_VOL = 0.02
M4_STAGED_REV_VOLUME = 0.9
M4_LAUNCH_CONTROL_THROTTLE_MIN = 0.55
M4_LAUNCH_CONTROL_THROTTLE_MAX = 0.85
M4_LAUNCH_CONTROL_HOLD_DURATION = 0.5
M4_LAUNCH_CONTROL_BRAKE_REQUIRED = False
M4_LAUNCH_CONTROL_ENGAGE_VOL = 1.0
M4_LAUNCH_CONTROL_HOLD_VOL = 1.0
M4_GESTURE_RETRIGGER_LOCKOUT = 0.3
M4_ACCELERATION_SOUND_OFFSET = 0.5

# M4 Moving Average Parameters
M4_RPM_IDLE = 800
M4_RPM_DECAY_RATE_PER_SEC = 1500
M4_RPM_DECAY_COOLDOWN_AFTER_REV = 0.1
M4_RPM_RESET_TO_IDLE_THRESHOLD_TIME = 6.0

# Supra specific parameters
SUPRA_NORMAL_IDLE_VOLUME = 0.7
SUPRA_LOW_IDLE_VOLUME_DURING_REV = 0.2
SUPRA_REV_GESTURE_WINDOW_TIME = 0.75
SUPRA_REV_RETRIGGER_LOCKOUT = 0.5
SUPRA_CLIP_OVERLAP_PREVENTION_TIME = 0.3
SUPRA_THROTTLE_STABILIZATION_DELAY = 0.8  # Time to wait for throttle to stabilize before selecting range
SUPRA_CROSSFADE_DURATION_MS = 800
SUPRA_IDLE_TRANSITION_SPEED = 2.5
SUPRA_CRUISE_TRANSITION_DELAY = 1.5  # Time before transitioning to cruise after pull/push
SUPRA_THROTTLE_CHANGE_THRESHOLD = 0.15  # Minimum throttle change to trigger immediate transition
SUPRA_HIGHWAY_CRUISE_THRESHOLD = 0.90  # Throttle threshold for highway cruise
SUPRA_THROTTLE_STABILITY_THRESHOLD = 0.05  # Max throttle variation to be considered "stable"

# Channel Definitions
M4_CH_IDLE = 0
M4_CH_TURBO_LIMITER_SFX = 1
M4_CH_LONG_SEQUENCE_A = 2
M4_CH_LONG_SEQUENCE_B = 3
M4_CH_STAGED_REV_SOUND = 4

SUPRA_CH_IDLE = 5
SUPRA_CH_DRIVING_A = 6
SUPRA_CH_DRIVING_B = 7
SUPRA_CH_REV_SFX = 8

# Sound file paths
M4_SOUND_FILES_PATH = "m4"
SUPRA_SOUND_FILES_PATH = "supra"

# GUI Configuration
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600
SLIDER_WIDTH = 400

# Global variables
running_simulation = True
log_data = []

class M4SoundManager:
    def __init__(self):
        self.sounds = {}
        self.rev_stages = []
        self.load_sounds()
        self.channel_idle = pygame.mixer.Channel(M4_CH_IDLE)
        self.channel_turbo_limiter_sfx = pygame.mixer.Channel(M4_CH_TURBO_LIMITER_SFX)
        
        self.channel_staged_rev = None
        if pygame.mixer.get_init() and pygame.mixer.get_num_channels() > M4_CH_STAGED_REV_SOUND:
            self.channel_staged_rev = pygame.mixer.Channel(M4_CH_STAGED_REV_SOUND)
        
        self.idle_target_volume = M4_NORMAL_IDLE_VOLUME
        self.idle_current_volume = M4_NORMAL_IDLE_VOLUME
        self.idle_is_fading = False

        self.waiting_for_launch_hold_loop = False
        self.launch_control_sounds_active = False
        self.just_switched_to_lc_hold = False
        self.channel_long_A = pygame.mixer.Channel(M4_CH_LONG_SEQUENCE_A)
        self.channel_long_B = pygame.mixer.Channel(M4_CH_LONG_SEQUENCE_B)
        self.active_long_channel = self.channel_long_A
        self.transitioning_long_sound = False
        self.transition_start_time = 0
        
        self.pending_offset_sounds = []

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
        snd, dur = self._load_sound_with_duration("engine_rev_stage1.wav")
        self.rev_stages.append({'key': 'rev_stage1', 'sound': snd, 'rpm_peak': 3000, 'duration': dur})
        snd, dur = self._load_sound_with_duration("engine_rev_stage2.wav")
        self.rev_stages.append({'key': 'rev_stage2', 'sound': snd, 'rpm_peak': 5000, 'duration': dur})
        snd, dur = self._load_sound_with_duration("engine_rev_stage3.wav")
        self.rev_stages.append({'key': 'rev_stage3', 'sound': snd, 'rpm_peak': 7000, 'duration': dur})
        snd, dur = self._load_sound_with_duration("engine_rev_stage4.wav")
        self.rev_stages.append({'key': 'rev_stage4', 'sound': snd, 'rpm_peak': 8500, 'duration': dur})

        self.sounds['turbo_bov'], _ = self._load_sound_with_duration("turbo_spool_and_bov.wav")
        self.sounds['rev_limiter'], _ = self._load_sound_with_duration("engine_high_rev_with_limiter.wav")
        
        self.sounds['accel_gears'], _ = self._load_sound_with_duration("acceleration_gears_1_to_4.wav")
        self.sounds['cruising'], _ = self._load_sound_with_duration("engine_cruising_loop.wav")
        self.sounds['decel_downshifts'], _ = self._load_sound_with_duration("deceleration_downshifts_to_idle.wav")
        self.sounds['starter'], _ = self._load_sound_with_duration("engine_starter.wav")
        self.sounds['launch_control_engage'], _ = self._load_sound_with_duration("launch_control_engage.wav")
        self.sounds['launch_control_hold_loop'], _ = self._load_sound_with_duration("launch_control_hold_loop.wav")

    def get_sound_name_from_obj(self, sound_obj):
        if sound_obj is None: return "None"
        for name, sound_asset_tuple in self.sounds.items():
            if name == 'idle':
                if self.sounds['idle'] == sound_obj: return "idle"
                continue
            if isinstance(sound_asset_tuple, pygame.mixer.Sound) and sound_asset_tuple == sound_obj:
                 return name
        for stage in self.rev_stages:
            if stage['sound'] == sound_obj:
                return stage['key']
        return "UnknownSoundObject"

    def update(self):
        self.just_switched_to_lc_hold = False
        
        current_time = time.time()
        sounds_to_remove = []
        for i, (sound_key, start_time, offset_duration, loops, channel_type) in enumerate(self.pending_offset_sounds):
            if current_time >= start_time + offset_duration:
                sound_info = self.sounds.get(sound_key)
                if sound_info and channel_type == 'long':
                    try:
                        self.active_long_channel.set_volume(MASTER_ENGINE_VOL)
                        self.active_long_channel.play(sound_info, loops=loops)
                        print(f"M4 Playing {sound_key} with {offset_duration}s offset simulation")
                    except Exception as e:
                        print(f"M4 Error playing offset sound {sound_key}: {e}")
                sounds_to_remove.append(i)
        
        for i in reversed(sounds_to_remove):
            self.pending_offset_sounds.pop(i)

        lc_engage_sound = self.sounds.get('launch_control_engage')
        lc_hold_sound = self.sounds.get('launch_control_hold_loop')
        current_sfx_sound_at_call = self.channel_turbo_limiter_sfx.get_sound()

        if self.waiting_for_launch_hold_loop:
            if not self.channel_turbo_limiter_sfx.get_busy() or current_sfx_sound_at_call != lc_engage_sound:
                if lc_hold_sound:
                    self.channel_turbo_limiter_sfx.set_volume(M4_LAUNCH_CONTROL_HOLD_VOL * MASTER_ENGINE_VOL)
                    self.channel_turbo_limiter_sfx.play(lc_hold_sound, loops=-1)
                    self.just_switched_to_lc_hold = True
                else:
                    self.launch_control_sounds_active = False
                self.waiting_for_launch_hold_loop = False
        
        if self.launch_control_sounds_active and not self.just_switched_to_lc_hold:
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
            return None

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
            self.just_switched_to_lc_hold = False
            return True
        elif hold_sound:
            print("M4 Launch control engage sound missing, playing hold loop directly.")
            self.channel_turbo_limiter_sfx.stop()
            self.channel_turbo_limiter_sfx.set_volume(M4_LAUNCH_CONTROL_HOLD_VOL * MASTER_ENGINE_VOL)
            self.channel_turbo_limiter_sfx.play(hold_sound, loops=-1)
            self.waiting_for_launch_hold_loop = False
            self.launch_control_sounds_active = True
            self.just_switched_to_lc_hold = True
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
        
        # Crossfading system
        self.transitioning_driving_sound = False
        self.transition_start_time = 0
        
        # State tracking
        self.last_clip_start_time = 0
        self.current_throttle_range = None  # Track current throttle range
        self.current_sound_type = None  # 'pull', 'push', 'cruise', 'highway_cruise'
        self.throttle_stable_start_time = None  # When throttle became stable in current range
        
        # Enhanced throttle stabilization
        self.recent_throttle_readings = collections.deque(maxlen=10)  # Store recent throttle values
        self.last_throttle_change_time = None  # When throttle last changed significantly

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
        essential_sounds = [
            ('idle', "supra_idle_loop.wav"),
            ('startup', "supra_startup.wav")
        ]
        
        missing_essential = []
        for key, filename in essential_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
            if self.sounds[key] is None:
                missing_essential.append(filename)
        
        if missing_essential:
            print(f"SUPRA CRITICAL ERROR: Missing essential sound files: {missing_essential}")
        
        light_sounds = [
            ('light_pull_1', "light_pull_1.wav"),
            ('light_pull_2', "light_pull_2.wav"),
            ('light_cruise_1', "light_cruise_1.wav"),
            ('light_cruise_2', "light_cruise_2.wav"),
            ('light_cruise_3', "light_cruise_3.wav")
        ]
        
        for key, filename in light_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
        
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
        
        violent_sounds = [
            ('violent_pull_1', "violent_pull_1.wav"),
            ('violent_pull_2', "violent_pull_2.wav"),
            ('violent_pull_3', "violent_pull_3.wav")
        ]
        
        for key, filename in violent_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)
        
        self.sounds['highway_cruise_loop'], _ = self._load_sound_with_duration("highway_cruise_loop.wav")
        
        # Separate cruise sounds from pull sounds for better logic
        self.light_pull_sounds = ['light_pull_1', 'light_pull_2']
        self.light_cruise_sounds = ['light_cruise_1', 'light_cruise_2', 'light_cruise_3']
        self.aggressive_push_sounds = ['aggressive_push_1', 'aggressive_push_2', 'aggressive_push_3', 
                                      'aggressive_push_4', 'aggressive_push_5', 'aggressive_push_6']
        self.violent_pull_sounds = ['violent_pull_1', 'violent_pull_2', 'violent_pull_3']
        
        rev_sounds = [
            ('rev_1', "supra_rev_1.wav"),
            ('rev_2', "supra_rev_2.wav"),
            ('rev_3', "supra_rev_3.wav")
        ]
        
        for key, filename in rev_sounds:
            self.sounds[key], _ = self._load_sound_with_duration(filename)

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

    def add_throttle_reading(self, throttle_percentage):
        """Add throttle reading and track stability"""
        current_time = time.time()
        self.recent_throttle_readings.append((current_time, throttle_percentage))
        
        # Check if throttle changed significantly
        if len(self.recent_throttle_readings) >= 2:
            prev_throttle = self.recent_throttle_readings[-2][1]
            if abs(throttle_percentage - prev_throttle) > SUPRA_THROTTLE_STABILITY_THRESHOLD:
                self.last_throttle_change_time = current_time
    
    def is_throttle_stable(self):
        """Check if throttle has been stable for the required duration"""
        current_time = time.time()
        
        if self.last_throttle_change_time is None:
            return False
        
        # Check if enough time has passed since last significant change
        time_since_change = current_time - self.last_throttle_change_time
        if time_since_change < SUPRA_THROTTLE_STABILIZATION_DELAY:
            return False
        
        # Verify throttle is actually stable by checking recent readings
        if len(self.recent_throttle_readings) < 5:
            return False
        
        recent_values = [reading[1] for reading in list(self.recent_throttle_readings)[-5:]]
        throttle_range = max(recent_values) - min(recent_values)
        
        return throttle_range <= SUPRA_THROTTLE_STABILITY_THRESHOLD
    
    def get_stable_throttle_range(self, current_throttle):
        """Get throttle range only if throttle is stable"""
        if not self.is_throttle_stable():
            return None
        return self.get_throttle_range(current_throttle)
    
    def reset_throttle_stabilization(self):
        self.recent_throttle_readings.clear()
        self.last_throttle_change_time = None

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
    
    def should_transition_immediately(self, new_throttle, current_range):
        """Determine if we should immediately transition due to significant throttle change"""
        if not self.is_driving_sound_busy():
            return False
        
        new_range = self.get_throttle_range(new_throttle)
        
        # If we changed throttle ranges, transition immediately
        if new_range != current_range:
            return True
        
        # If throttle changed significantly within the same range during cruise
        if self.current_sound_type in ['cruise', 'highway_cruise']:
            # Check for significant throttle change
            throttle_change = abs(new_throttle - self.get_range_center(current_range))
            if throttle_change > SUPRA_THROTTLE_CHANGE_THRESHOLD:
                return True
        
        return False
    
    def get_range_center(self, range_name):
        """Get the center throttle value for a range"""
        range_centers = {
            'light': 0.20,
             'aggressive': 0.45,
            'violent': 0.80,
            'highway': 0.95
        }
        return range_centers.get(range_name, 0.5)
    
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
        self.sm.update()

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
            if self.current_throttle >= 0.98:
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
        
        # Rev gesture detection (preserved from original)
        self.in_potential_rev_gesture = False
        self.rev_gesture_start_time = 0.0
        self.peak_throttle_in_rev_gesture = 0.0
        self.rev_gesture_lockout_until_time = 0.0
        
        # New cruise state management
        self.current_throttle_range = None
        self.throttle_stable_time = None
        self.last_significant_throttle_change = None

    def update(self, dt, new_throttle_value):
        previous_throttle = self.current_throttle
        self.current_throttle = new_throttle_value
        current_time = time.time()
        
        self.throttle_history.append((current_time, self.current_throttle))
        self.sm.update_idle_fade(dt)
        self.sm.update_driving_crossfade()  # Update crossfade transitions
        
        # Track throttle range changes
        new_throttle_range = self.sm.get_throttle_range(self.current_throttle)
        if new_throttle_range != self.current_throttle_range:
            self.current_throttle_range = new_throttle_range
            self.last_significant_throttle_change = current_time
            self.throttle_stable_time = None
        elif self.throttle_stable_time is None and self.current_throttle_range != 'idle':
            # Start tracking stability when we stay in the same range
            self.throttle_stable_time = current_time
        
        # Handle idle volume restoration
        if self.state == "IDLE" and not self.sm.is_rev_sound_busy():
            if abs(self.sm.idle_target_volume - SUPRA_NORMAL_IDLE_VOLUME) > 0.01:
                self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
            if not self.sm.channel_idle.get_busy():
                self.sm.play_idle()

        # State machine
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
            
            # Transition from idle when throttle is applied AND STABLE
            if self.current_throttle >= 0.10:
                # Add throttle reading for stability tracking
                self.sm.add_throttle_reading(self.current_throttle)
                
                # Only transition if throttle is stable
                stable_range = self.sm.get_stable_throttle_range(self.current_throttle)
                if stable_range and stable_range != 'idle' and not self.sm.is_driving_sound_busy():
                    if self.sm.play_driving_sound(self.current_throttle, force_type='pull'):
                        self.state = "PULL"
                        self.range_when_pull_started = stable_range
                        self.pull_start_time = current_time
                        self.sm.set_idle_target_volume(0.0)
                        print(f"\nSupra IDLE -> PULL ({stable_range} range) at {self.current_throttle:.2f} (waited for stability)")
            else:
                # Reset stabilization when back at idle throttle
                self.sm.reset_throttle_stabilization()

        elif self.state == "PULL":
            self._handle_driving_state(current_time, "PULL")

        elif self.state == "CRUISE":
            self._handle_driving_state(current_time, "CRUISE")

    def _handle_driving_state(self, current_time, current_state):
        """Handle logic for PULL and CRUISE states"""
        
        # Check if we should return to idle
        if self.current_throttle < 0.05:
            print(f"\nSupra returning to idle from {current_state}")
            self.state = "IDLE"
            self.sm.stop_driving_sounds(fade_ms=SUPRA_CROSSFADE_DURATION_MS // 2)
            self.sm.set_idle_target_volume(SUPRA_NORMAL_IDLE_VOLUME)
            self.sm.play_idle()
            return
        
        # Check for immediate transitions due to significant throttle changes
        if self.sm.should_transition_immediately(self.current_throttle, self.current_throttle_range):
            new_range = self.sm.get_throttle_range(self.current_throttle)
            print(f"\nSupra immediate transition: {current_state} -> PULL (range changed {self.current_throttle_range} -> {new_range})")
            
            # Crossfade to appropriate pull/push sound for new range
            if self.sm.play_driving_sound(self.current_throttle, force_type='pull', crossfade=True):
                self.state = "PULL"
                self.throttle_stable_time = None
            return
        
        # Handle transition from PULL to CRUISE after stability period
        if current_state == "PULL" and not self.sm.is_driving_sound_busy():
            if (self.throttle_stable_time is not None and 
                current_time - self.throttle_stable_time >= SUPRA_CRUISE_TRANSITION_DELAY):
                
                # Transition to appropriate cruise sound
                cruise_type = 'highway_cruise' if self.current_throttle_range == 'highway' else 'cruise'
                
                if self.sm.play_driving_sound(self.current_throttle, force_type=cruise_type):
                    self.state = "CRUISE"
                    print(f"\nSupra transitioning PULL -> CRUISE ({cruise_type}) at {self.current_throttle:.2f}")
                else:
                    # Fallback: play another pull sound if cruise not available
                    if self.sm.play_driving_sound(self.current_throttle, force_type='pull'):
                        print(f"\nSupra continuing PULL (cruise not available) at {self.current_throttle:.2f}")
            else:
                # Continue with another pull/push sound
                if self.sm.play_driving_sound(self.current_throttle, force_type='pull'):
                    print(f"\nSupra continuing PULL at {self.current_throttle:.2f}")
        
        # Handle CRUISE state - check if cruise sound stopped (shouldn't happen with looping)
        elif current_state == "CRUISE" and not self.sm.is_driving_sound_busy():
            # Restart cruise sound
            cruise_type = 'highway_cruise' if self.current_throttle_range == 'highway' else 'cruise'
            if self.sm.play_driving_sound(self.current_throttle, force_type=cruise_type):
                print(f"\nSupra restarting CRUISE ({cruise_type}) at {self.current_throttle:.2f}")

    def _check_rev_gestures(self, current_time, old_throttle_value):
        """Rev gesture detection (preserved from original logic)"""
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
            return
        
        new_car = "Supra" if self.current_car == "M4" else "M4"
        print(f"\nSwitching from {self.current_car} to {new_car}...")
        self.switching_cars = True
        self.switch_start_time = time.time()
        
        if self.current_car == "M4":
            self.m4_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)
        else:
            self.supra_sound_manager.fade_out_all_sounds(SUPRA_CROSSFADE_DURATION_MS)

    def update(self, dt, raw_throttle):
        self.throttle_buffer.append(raw_throttle)
        smoothed_throttle = sum(self.throttle_buffer) / len(self.throttle_buffer)
        
        current_time = time.time()
        
        if self.switching_cars:
            if current_time - self.switch_start_time >= (SUPRA_CROSSFADE_DURATION_MS / 1000.0):
                if self.current_car == "M4":
                    self.m4_sound_manager.stop_all_sounds()
                    self.current_car = "Supra"
                    self.supra_engine.state = "ENGINE_OFF"
                    print("Switched to Supra")
                else:
                    self.supra_sound_manager.stop_all_sounds()
                    self.current_car = "M4"
                    self.m4_engine.state = "ENGINE_OFF"
                    print("Switched to M4")
                
                self.switching_cars = False
            else:
                return smoothed_throttle, raw_throttle
        
        if self.current_car == "M4":
            self.m4_engine.update(dt, smoothed_throttle)
        else:
            self.supra_engine.update(dt, smoothed_throttle)
        
        return smoothed_throttle, raw_throttle

    def get_active_engine(self):
        return self.m4_engine if self.current_car == "M4" else self.supra_engine

    def get_active_sound_manager(self):
        return self.m4_sound_manager if self.current_car == "M4" else self.supra_sound_manager

class ThrottleSimulatorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Throttle Simulator - ThrottleTune")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.configure(bg='#1e1e1e')
        
        self.throttle_value = tk.DoubleVar(value=0.0)
        self.dual_car_system = None
        self.simulation_thread = None
        self.running = False
        
        self.setup_gui()
        self.initialize_audio()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_gui(self):
        title_frame = tk.Frame(self.root, bg='#1e1e1e')
        title_frame.pack(pady=20)
        
        title_label = tk.Label(title_frame, text="ThrottleTune Simulator", 
                              font=('Arial', 24, 'bold'), fg='#ffffff', bg='#1e1e1e')
        title_label.pack()
        
        subtitle_label = tk.Label(title_frame, text="Dynamic Throttle Control", 
                                 font=('Arial', 12), fg='#cccccc', bg='#1e1e1e')
        subtitle_label.pack()

        main_frame = tk.Frame(self.root, bg='#1e1e1e')
        main_frame.pack(expand=True, fill='both', padx=40, pady=20)

        throttle_frame = tk.Frame(main_frame, bg='#2d2d2d', relief='raised', bd=2)
        throttle_frame.pack(pady=20, padx=20, fill='x')
        
        throttle_label = tk.Label(throttle_frame, text="Throttle Position", 
                                 font=('Arial', 16, 'bold'), fg='#ffffff', bg='#2d2d2d')
        throttle_label.pack(pady=(10, 5))
        
        self.throttle_percent_label = tk.Label(throttle_frame, text="0.0%", 
                                              font=('Arial', 28, 'bold'), fg='#00ff00', bg='#2d2d2d')
        self.throttle_percent_label.pack(pady=5)
        
        slider_frame = tk.Frame(throttle_frame, bg='#2d2d2d')
        slider_frame.pack(pady=10, fill='x', padx=20)
        
        self.throttle_slider = tk.Scale(slider_frame, from_=0, to=100, 
                                       orient='horizontal', length=SLIDER_WIDTH,
                                       variable=self.throttle_value, resolution=0.1,
                                       command=self.on_throttle_change,
                                       bg='#2d2d2d', fg='#ffffff', highlightbackground='#2d2d2d',
                                       troughcolor='#444444', activebackground='#666666')
        self.throttle_slider.pack()
        
        range_frame = tk.Frame(throttle_frame, bg='#2d2d2d')
        range_frame.pack(pady=5)
        
        tk.Label(range_frame, text="0%", font=('Arial', 10), fg='#cccccc', bg='#2d2d2d').pack(side='left')
        tk.Label(range_frame, text="50%", font=('Arial', 10), fg='#cccccc', bg='#2d2d2d').pack()
        tk.Label(range_frame, text="100%", font=('Arial', 10), fg='#cccccc', bg='#2d2d2d').pack(side='right')

        controls_frame = tk.Frame(main_frame, bg='#2d2d2d', relief='raised', bd=2)
        controls_frame.pack(pady=20, padx=20, fill='x')
        
        controls_label = tk.Label(controls_frame, text="Controls", 
                                 font=('Arial', 16, 'bold'), fg='#ffffff', bg='#2d2d2d')
        controls_label.pack(pady=(10, 5))
        
        buttons_frame = tk.Frame(controls_frame, bg='#2d2d2d')
        buttons_frame.pack(pady=10)
        
        self.start_button = tk.Button(buttons_frame, text="Start Simulation", 
                                     command=self.start_simulation,
                                     font=('Arial', 12, 'bold'), bg='#4CAF50', fg='white',
                                     padx=20, pady=10, relief='raised', bd=2)
        self.start_button.pack(side='left', padx=10)
        
        self.stop_button = tk.Button(buttons_frame, text="Stop Simulation", 
                                    command=self.stop_simulation,
                                    font=('Arial', 12, 'bold'), bg='#f44336', fg='white',
                                    padx=20, pady=10, relief='raised', bd=2, state='disabled')
        self.stop_button.pack(side='left', padx=10)
        
        self.switch_button = tk.Button(buttons_frame, text="Switch Car (M4 ⇌ Supra)", 
                                      command=self.switch_car,
                                      font=('Arial', 12, 'bold'), bg='#2196F3', fg='white',
                                      padx=20, pady=10, relief='raised', bd=2, state='disabled')
        self.switch_button.pack(side='left', padx=10)

        status_frame = tk.Frame(main_frame, bg='#2d2d2d', relief='raised', bd=2)
        status_frame.pack(pady=20, padx=20, fill='both', expand=True)
        
        status_label = tk.Label(status_frame, text="Engine Status", 
                               font=('Arial', 16, 'bold'), fg='#ffffff', bg='#2d2d2d')
        status_label.pack(pady=(10, 5))
        
        self.car_label = tk.Label(status_frame, text="Current Car: N/A", 
                                 font=('Arial', 14, 'bold'), fg='#ffaa00', bg='#2d2d2d')
        self.car_label.pack(pady=2)
        
        self.state_label = tk.Label(status_frame, text="Engine State: N/A", 
                                   font=('Arial', 12), fg='#ffffff', bg='#2d2d2d')
        self.state_label.pack(pady=2)
        
        self.rpm_label = tk.Label(status_frame, text="Simulated RPM: N/A", 
                                 font=('Arial', 12), fg='#ffffff', bg='#2d2d2d')
        self.rpm_label.pack(pady=2)
        
        self.status_label = tk.Label(status_frame, text="Status: Ready", 
                                    font=('Arial', 12), fg='#00ff00', bg='#2d2d2d')
        self.status_label.pack(pady=5)

    def initialize_audio(self):
        try:
            pygame.init()
            pygame.mixer.init(frequency=MIXER_FREQUENCY, size=MIXER_SIZE, 
                            channels=MIXER_CHANNELS_STEREO, buffer=MIXER_BUFFER)
            if pygame.mixer.get_init():
                pygame.mixer.set_num_channels(NUM_PYGAME_MIXER_CHANNELS)
                print(f"Audio initialized with {pygame.mixer.get_num_channels()} channels")
                self.status_label.config(text="Status: Audio initialized", fg='#00ff00')
            else:
                print("Failed to initialize audio mixer")
                self.status_label.config(text="Status: Audio initialization failed", fg='#ff0000')
        except Exception as e:
            print(f"Audio initialization error: {e}")
            self.status_label.config(text=f"Status: Audio error - {e}", fg='#ff0000')

    def on_throttle_change(self, value):
        percentage = float(value)
        self.throttle_percent_label.config(text=f"{percentage:.1f}%")
        
        # Dynamic color based on throttle position
        if percentage < 30:
            color = '#00ff00'  # Green
        elif percentage < 70:
            color = '#ffaa00'  # Orange
        else:
            color = '#ff0000'  # Red
        
        self.throttle_percent_label.config(fg=color)

    def start_simulation(self):
        if not self.running:
            try:
                os.makedirs(M4_SOUND_FILES_PATH, exist_ok=True)
                os.makedirs(SUPRA_SOUND_FILES_PATH, exist_ok=True)
                
                self.dual_car_system = DualCarSystem()
                self.running = True
                
                self.simulation_thread = threading.Thread(target=self.simulation_loop, daemon=True)
                self.simulation_thread.start()
                
                self.start_button.config(state='disabled')
                self.stop_button.config(state='normal')
                self.switch_button.config(state='normal')
                
                self.status_label.config(text="Status: Simulation running", fg='#00ff00')
                print("Simulation started")
            except Exception as e:
                print(f"Failed to start simulation: {e}")
                self.status_label.config(text=f"Status: Failed to start - {e}", fg='#ff0000')

    def stop_simulation(self):
        if self.running:
            self.running = False
            
            if self.dual_car_system:
                self.dual_car_system.m4_sound_manager.stop_all_sounds()
                self.dual_car_system.supra_sound_manager.stop_all_sounds()
            
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            self.switch_button.config(state='disabled')
            
            self.car_label.config(text="Current Car: N/A")
            self.state_label.config(text="Engine State: N/A")
            self.rpm_label.config(text="Simulated RPM: N/A")
            self.status_label.config(text="Status: Simulation stopped", fg='#ffaa00')
            
            print("Simulation stopped")

    def switch_car(self):
        if self.dual_car_system and self.running:
            self.dual_car_system.switch_car()

    def simulation_loop(self):
        last_time = time.time()
        
        while self.running:
            current_time = time.time()
            dt = current_time - last_time
            if dt <= 0:
                dt = 1/FPS
            last_time = current_time
            
            # Get throttle value (convert from 0-100 to 0-1)
            raw_throttle = self.throttle_value.get() / 100.0
            
            # Update the dual car system
            if self.dual_car_system:
                smoothed_throttle, _ = self.dual_car_system.update(dt, raw_throttle)
                
                # Update GUI status
                self.root.after(0, self.update_status_display, smoothed_throttle)
            
            # Maintain target FPS
            processing_time = time.time() - current_time
            sleep_duration = max(0, (1.0 / FPS) - processing_time)
            time.sleep(sleep_duration)

    def update_status_display(self, throttle_value):
        if self.dual_car_system and self.running:
            active_engine = self.dual_car_system.get_active_engine()
            current_car = self.dual_car_system.current_car
            
            self.car_label.config(text=f"Current Car: {current_car}")
            self.state_label.config(text=f"Engine State: {active_engine.state}")
            
            if hasattr(active_engine, 'simulated_rpm'):
                self.rpm_label.config(text=f"Simulated RPM: {active_engine.simulated_rpm:.0f}")
            else:
                self.rpm_label.config(text="Simulated RPM: N/A")

    def on_closing(self):
        global running_simulation
        running_simulation = False
        self.stop_simulation()
        
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        if pygame.get_init():
            pygame.quit()
        
        self.root.destroy()

    def run(self):
        self.root.mainloop()

def main():
    print("ThrottleTune Throttle Simulator")
    print("================================")
    print("A GUI-based throttle simulator for testing engine sound logic")
    print("Use the slider to control throttle position dynamically")
    print("Press 'Switch Car' to toggle between M4 and Supra engines")
    print("")
    
    # Check for sound files
    if not os.path.exists(M4_SOUND_FILES_PATH):
        print(f"Warning: M4 sound directory '{M4_SOUND_FILES_PATH}' not found")
    if not os.path.exists(SUPRA_SOUND_FILES_PATH):
        print(f"Warning: Supra sound directory '{SUPRA_SOUND_FILES_PATH}' not found")
    
    try:
        app = ThrottleSimulatorGUI()
        app.run()
    except Exception as e:
        print(f"Application error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()