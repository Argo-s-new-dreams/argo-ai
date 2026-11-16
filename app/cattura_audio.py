"""cattura_audio.py - cattura dal microfono e dall'audio del computer, mescolati in un'unica traccia.

Serve alla pagina Registra: nelle call Teams il microfono sente solo chi usa Argo, le voci degli altri
partecipanti escono dagli altoparlanti. Per averle si cattura anche l'audio del computer:

    Windows  WASAPI loopback (libreria PyAudioWPatch), nessun programma da installare
    macOS    ScreenCaptureKit (macOS 13+, pyobjc-framework-ScreenCaptureKit), chiede il permesso
             «Registrazione schermo e audio di sistema» la prima volta
    ovunque  ripiego su un dispositivo di loopback già presente (BlackHole, Missaggio stereo, CABLE…)

Tutto resta in memoria: chi usa il Mixer decide se scrivere su file (Archivia) o tagliare in blocchi
temporanei (Live). Uscita sempre a 16 kHz mono float32, il formato di WhisperX.
"""
import collections
import sys
import threading
import time

import numpy as np

SR = 16000
NOMI_LOOPBACK = ("blackhole", "loopback", "stereo mix", "missaggio stereo", "soundflower", "cable output",
                 "what u hear", "monitor of")


# =============================================================== ricampionamento con stato
class Ricampionatore:
    """Porta un flusso continuo a 16 kHz senza «clic» ai bordi dei blocchi.
    Rapporto intero (48 kHz, 32 kHz…): filtro passa-basso con stato + decimazione con fase conservata.
    Altri rapporti (44,1 kHz): resample_poly a blocchi, accettabile per la voce."""

    def __init__(self, sr_in):
        self.sr_in = int(sr_in)
        self.fattore = self.sr_in // SR if self.sr_in % SR == 0 else 0
        self.zi = None
        self.fase = 0
        if self.fattore > 1:
            from scipy.signal import firwin, lfilter_zi
            self.h = firwin(63, 0.9 / self.fattore)
            self.zi = lfilter_zi(self.h, 1.0) * 0.0

    def __call__(self, x):
        x = np.asarray(x, dtype=np.float32)
        if self.sr_in == SR or not len(x):
            return x
        if self.fattore > 1:
            from scipy.signal import lfilter
            y, self.zi = lfilter(self.h, 1.0, x, zi=self.zi)
            out = y[self.fase::self.fattore]
            self.fase = (self.fase - len(x)) % self.fattore
            return out.astype(np.float32)
        from math import gcd

        from scipy.signal import resample_poly
        g = gcd(SR, self.sr_in)
        return resample_poly(x, SR // g, self.sr_in // g).astype(np.float32)


# =============================================================== sorgenti
class Sorgente:
    """Base: un thread esterno (callback audio) chiama _metti(); il mixer chiama leggi()."""
    nome = "sorgente"

    def __init__(self):
        self._buf = collections.deque()
        self._lock = threading.Lock()
        self.livello = 0.0
        self.errore = ""
        self._ric = None

    def _metti(self, x, sr):
        if self._ric is None or self._ric.sr_in != int(sr):
            self._ric = Ricampionatore(sr)
        y = self._ric(x)
        if len(y):
            self.livello = float(np.sqrt(np.mean(y ** 2)))
            with self._lock:
                self._buf.append(y)

    def leggi(self):
        with self._lock:
            parti = list(self._buf)
            self._buf.clear()
        return np.concatenate(parti) if parti else np.zeros(0, np.float32)

    def avvia(self):
        raise NotImplementedError

    def ferma(self):
        pass


class Microfono(Sorgente):
    nome = "Microfono"

    def __init__(self, dispositivo=None):
        super().__init__()
        self.dispositivo = dispositivo or None  # nome del dispositivo, None = predefinito
        self.flusso = None

    def avvia(self):
        import sounddevice as sd
        indice = None
        if self.dispositivo:
            indice = indice_dispositivo(self.dispositivo)
            if indice is None:
                raise RuntimeError(f"microfono «{self.dispositivo}» non trovato (scollegato?)")
            self.nome = f"Microfono ({self.dispositivo})"
        else:
            try:
                self.nome = f"Microfono ({sd.query_devices(kind='input')['name']})"
            except Exception:
                pass
        self.flusso = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=indice,
                                     callback=lambda d, *_: self._metti(d[:, 0].copy(), SR))
        self.flusso.start()

    def ferma(self):
        if self.flusso:
            self.flusso.stop()
            self.flusso.close()
            self.flusso = None


class DispositivoLoopback(Sorgente):
    """Ripiego: un dispositivo d'ingresso che riceve l'audio del computer (BlackHole, Missaggio stereo…)."""

    def __init__(self, indice, nome):
        super().__init__()
        self.indice = indice
        self.nome = f"Audio del computer ({nome})"
        self.flusso = None

    @staticmethod
    def trova():
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0 and any(k in d["name"].lower() for k in NOMI_LOOPBACK):
                    return i, d["name"]
        except Exception:
            pass
        return None

    def avvia(self):
        import sounddevice as sd
        info = sd.query_devices(self.indice)
        canali = min(2, int(info["max_input_channels"]))
        sr = int(info.get("default_samplerate") or 48000)
        self.flusso = sd.InputStream(samplerate=sr, channels=canali, dtype="float32", device=self.indice,
                                     callback=lambda d, *_: self._metti(d.mean(axis=1), sr))
        self.flusso.start()

    def ferma(self):
        if self.flusso:
            self.flusso.stop()
            self.flusso.close()
            self.flusso = None


class LoopbackWindows(Sorgente):
    """Windows: l'audio che esce dagli altoparlanti predefiniti, con WASAPI loopback (PyAudioWPatch)."""
    nome = "Audio del computer (Windows)"

    def __init__(self):
        super().__init__()
        self.pa = None
        self.flusso = None

    def avvia(self):
        import pyaudiowpatch as pyaudio
        self.pa = pyaudio.PyAudio()
        wasapi = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        uscita = self.pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if not uscita.get("isLoopbackDevice"):
            for lb in self.pa.get_loopback_device_info_generator():
                if uscita["name"] in lb["name"]:
                    uscita = lb
                    break
            else:
                raise RuntimeError("nessun dispositivo di loopback per gli altoparlanti predefiniti")
        canali = int(uscita["maxInputChannels"]) or 2
        sr = int(uscita["defaultSampleRate"])
        self.nome = f"Audio del computer ({uscita['name'].split(' [Loopback]')[0]})"

        def cb(dati, n, info, stato):
            x = np.frombuffer(dati, dtype=np.float32).reshape(-1, canali).mean(axis=1)
            self._metti(x, sr)
            return None, pyaudio.paContinue

        self.flusso = self.pa.open(format=pyaudio.paFloat32, channels=canali, rate=sr, input=True,
                                   input_device_index=uscita["index"], frames_per_buffer=int(sr // 20),
                                   stream_callback=cb)
        self.flusso.start_stream()

    def ferma(self):
        try:
            if self.flusso:
                self.flusso.stop_stream()
                self.flusso.close()
        finally:
            self.flusso = None
            if self.pa:
                self.pa.terminate()
                self.pa = None


class AudioSistemaMac(Sorgente):
    """macOS 13+: audio di sistema con ScreenCaptureKit (serve il permesso Registrazione schermo e audio).
    Lo schermo non viene registrato: il flusso video è ridotto a 2x2 pixel, 1 fotogramma al secondo, e scartato."""
    nome = "Audio del computer (macOS)"
    SR_MAC = 48000

    def __init__(self):
        super().__init__()
        self.stream = None
        self._uscita = None

    def avvia(self):
        import CoreMedia as CM
        import objc
        import ScreenCaptureKit as SCK
        from Foundation import NSObject

        sorgente = self

        if not hasattr(AudioSistemaMac, "_Classe"):
            try:
                protocolli = [objc.protocolNamed("SCStreamOutput")]
            except Exception:  # la firma del metodo arriva comunque dai metadati di PyObjC
                protocolli = []

            class ArgoUscitaAudio(NSObject, protocols=protocolli):
                def stream_didOutputSampleBuffer_ofType_(self, stream, campione, tipo):
                    if tipo != SCK.SCStreamOutputTypeAudio:
                        return
                    try:
                        blocco = CM.CMSampleBufferGetDataBuffer(campione)
                        n = CM.CMBlockBufferGetDataLength(blocco)
                        err, dati = CM.CMBlockBufferCopyDataBytes(blocco, 0, n, None)
                        if err == 0 and dati:
                            x = np.frombuffer(bytes(dati), dtype=np.float32)
                            campioni = int(CM.CMSampleBufferGetNumSamples(campione) or 0)
                            canali = len(x) // campioni if campioni else 1
                            if canali > 1:  # float32 non interlacciato: un piano per canale
                                x = x[: canali * campioni].reshape(canali, campioni).mean(axis=0)
                            AudioSistemaMac.attiva._metti(x.copy(), AudioSistemaMac.SR_MAC)
                    except Exception as e:  # pragma: no cover - dipende da macOS
                        AudioSistemaMac.attiva.errore = str(e)

            AudioSistemaMac._Classe = ArgoUscitaAudio

        pronto, risultato = threading.Event(), {}

        def contenuti(c, err):
            risultato["c"], risultato["e"] = c, err
            pronto.set()

        SCK.SCShareableContent.getShareableContentWithCompletionHandler_(contenuti)
        if not pronto.wait(10):
            raise RuntimeError("macOS non ha risposto alla richiesta di cattura")
        if risultato.get("e") or not risultato.get("c") or not risultato["c"].displays():
            raise RuntimeError("permesso negato: abilita Argo AI in Impostazioni di Sistema → Privacy e sicurezza → "
                               "Registrazione schermo e audio di sistema, poi riapri Argo")
        filtro = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(risultato["c"].displays()[0], [])
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setCapturesAudio_(True)
        cfg.setExcludesCurrentProcessAudio_(True)
        cfg.setSampleRate_(self.SR_MAC)
        cfg.setChannelCount_(1)
        cfg.setWidth_(2)
        cfg.setHeight_(2)
        cfg.setMinimumFrameInterval_(CM.CMTimeMake(1, 1))
        self.stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(filtro, cfg, None)
        AudioSistemaMac.attiva = sorgente  # una sola cattura alla volta
        self._uscita = AudioSistemaMac._Classe.alloc().init()
        esito = self.stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._uscita, SCK.SCStreamOutputTypeAudio, None, None)
        if isinstance(esito, tuple) and not esito[0]:
            raise RuntimeError(f"impossibile ricevere l'audio: {esito[1]}")
        avviato, errore = threading.Event(), {}

        def partito(err):
            errore["e"] = err
            avviato.set()

        self.stream.startCaptureWithCompletionHandler_(partito)
        if not avviato.wait(10):
            raise RuntimeError("la cattura dell'audio di sistema non è partita")
        if errore.get("e"):
            raise RuntimeError(f"cattura non avviata: {errore['e']}")

    def ferma(self):
        if self.stream:
            fatto = threading.Event()
            try:
                self.stream.stopCaptureWithCompletionHandler_(lambda err: fatto.set())
                fatto.wait(5)
            except Exception:
                pass
            self.stream = None


def _dispositivi_ingresso():
    try:
        import sounddevice as sd
        return [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d.get("max_input_channels", 0) > 0]
    except Exception:
        return []


def elenco_microfoni():
    """[(valore, etichetta)]: «» = microfono predefinito del sistema, altrimenti il nome del dispositivo."""
    out = [("", "Predefinito del sistema")]
    for _, nome in _dispositivi_ingresso():
        if not any(k in nome.lower() for k in NOMI_LOOPBACK):
            out.append((nome, nome))
    return out


def elenco_sistema():
    """[(valore, etichetta)] per l'audio del computer. I dispositivi si salvano per nome (gli indici cambiano)."""
    out = [("auto", "Automatico (consigliato)"), ("nessuna", "Nessuno: solo microfono")]
    if sys.platform == "darwin":
        out.append(("nativo", "Audio di sistema macOS (ScreenCaptureKit)"))
    elif sys.platform == "win32":
        out.append(("nativo", "Altoparlanti predefiniti di Windows (WASAPI)"))
    for _, nome in _dispositivi_ingresso():
        if any(k in nome.lower() for k in NOMI_LOOPBACK):
            out.append(("dev:" + nome, nome))
    return out


def indice_dispositivo(nome):
    for i, n in _dispositivi_ingresso():
        if n == nome:
            return i
    return None


def sorgente_sistema(scelta="auto"):
    """Avvia la sorgente scelta per l'audio del computer: (sorgente, "") oppure (None, motivo).
    scelta: "auto" | "nessuna" | "nativo" | "dev:<nome dispositivo>"."""
    if scelta == "nessuna":
        return None, ""
    if scelta.startswith("dev:"):
        nome = scelta[4:]
        i = indice_dispositivo(nome)
        if i is None:
            return None, f"dispositivo «{nome}» non trovato (scollegato?)"
        try:
            s = DispositivoLoopback(i, nome)
            s.avvia()
            return s, ""
        except Exception as e:
            return None, f"{nome}: {e}"
    tentativi = []
    if sys.platform == "darwin":
        tentativi.append(AudioSistemaMac)
    elif sys.platform == "win32":
        tentativi.append(LoopbackWindows)
    motivi = []
    for cls in tentativi:
        try:
            s = cls()
            s.avvia()
            return s, ""
        except Exception as e:
            motivi.append(f"{cls.nome}: {e}")
    if scelta == "nativo":
        return None, "; ".join(motivi) or "non disponibile su questo sistema"
    trovato = DispositivoLoopback.trova()
    if trovato:
        try:
            s = DispositivoLoopback(*trovato)
            s.avvia()
            return s, ""
        except Exception as e:
            motivi.append(f"{trovato[1]}: {e}")
    if not tentativi and not trovato:
        motivi.append("su questo sistema serve un dispositivo di loopback")
    return None, "; ".join(motivi)


# =============================================================== mixer
class Mixer:
    """Mescola microfono e audio del computer e consegna blocchi a 16 kHz mono a `uscita(x)`, ogni 100 ms.
    Il microfono fa da orologio; l'audio del computer (che durante i silenzi può non arrivare) viene allineato,
    riempito di zeri se manca e sfoltito se si accumula troppo."""
    PASSO = 0.1
    MAX_RITARDO = 2.0  # secondi di audio del computer in attesa oltre i quali si scarta il più vecchio

    def __init__(self, uscita, sistema="auto", guadagno_mic=1.0, guadagno_sis=1.0, microfono=None):
        """sistema: "auto" | "nessuna" | "nativo" | "dev:<nome>" (True/False per compatibilità).
        I guadagni si possono cambiare durante la registrazione."""
        self.uscita = uscita
        self.scelta_sistema = {True: "auto", False: "nessuna"}.get(sistema, sistema)
        self.microfono = microfono
        self.g_mic, self.g_sis = guadagno_mic, guadagno_sis
        self.mic = None
        self.sis = None
        self.avviso_sistema = ""
        self._attesa = np.zeros(0, np.float32)
        self._thread = None
        self._stop = threading.Event()
        self.campioni = 0
        self.errore = ""

    @property
    def secondi(self):
        return self.campioni / SR

    def avvia(self):
        self.mic = Microfono(self.microfono)
        self.mic.avvia()
        self.sis, self.avviso_sistema = sorgente_sistema(self.scelta_sistema)
        self._stop.clear()
        self._thread = threading.Thread(target=self._ciclo, name="argo-mixer", daemon=True)
        self._thread.start()

    def _ciclo(self):
        while not self._stop.wait(self.PASSO):
            self._passo()
        self._passo()

    def _passo(self):
        try:
            m = self.mic.leggi() if self.mic else np.zeros(0, np.float32)
            if not len(m):
                return
            x = self.mescola(m, self.sis.leggi() if self.sis else None)
            self.campioni += len(x)
            self.uscita(x)
        except Exception as e:  # non fermare la registrazione per un blocco andato storto
            self.errore = str(e)

    def mescola(self, m, s=None):
        """Allinea l'audio del computer alla durata del blocco del microfono e somma."""
        if s is not None and len(s):
            self._attesa = np.concatenate([self._attesa, s])
        if len(self._attesa) > self.MAX_RITARDO * SR:
            self._attesa = self._attesa[-int(self.MAX_RITARDO * SR):]
        n = len(m)
        parte = self._attesa[:n]
        self._attesa = self._attesa[n:]
        if len(parte) < n:
            parte = np.concatenate([parte, np.zeros(n - len(parte), np.float32)])
        return np.clip(m * self.g_mic + parte * self.g_sis, -1.0, 1.0).astype(np.float32)

    def livelli(self):
        return (self.mic.livello if self.mic else 0.0), (self.sis.livello if self.sis else 0.0)

    def ferma(self):
        self._stop.set()
        for s in (self.mic, self.sis):
            try:
                if s:
                    s.ferma()
            except Exception:
                pass
        if self._thread:
            self._thread.join(3)
            self._thread = None


def scrivi_wav(percorso, x):
    import wave
    with wave.open(str(percorso), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def leggi_wav(percorso):
    import wave
    with wave.open(str(percorso), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


if __name__ == "__main__":  # prova rapida: 10 secondi su prova_cattura.wav
    parti = []
    mx = Mixer(parti.append)
    mx.avvia()
    print("Sorgenti:", mx.mic.nome, "+", mx.sis.nome if mx.sis else f"(nessun audio del computer: {mx.avviso_sistema})")
    for _ in range(10):
        time.sleep(1)
        print("livelli mic %.3f  sistema %.3f" % mx.livelli())
    mx.ferma()
    scrivi_wav("prova_cattura.wav", np.concatenate(parti) if parti else np.zeros(0))
    print("Scritto prova_cattura.wav")
