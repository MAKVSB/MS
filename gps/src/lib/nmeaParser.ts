// src/lib/nmeaParser.ts

import type { GpsDataPoint, SatelliteInfo } from "./interfaces";
import {
  convertNmeaCoordToDecimal,
  createDateFromNmea,
  parseNumber,
} from "./utils";

// Pole se satelitními informacemi pro aktuální časový slot
interface SatelliteDataCache {
  [prn: number]: Partial<SatelliteInfo>;
}

export class NmeaParser {
  // Cache pro shromáždění dat z různých vět s jedním časovým razítkem (obvykle 1 sekunda)
  private _dataCache: Partial<GpsDataPoint> = {};
  private _satelliteCache: SatelliteDataCache = {};
  private _lastTimestamp: string | null = null;
  private _lastDate: string | null = null;
  private _gnssType: "GPS" | "GLONASS" | "Combined" | "Unknown" = "Unknown";

  // Uloží kompletní body čekající na export (může se hodit pro synchronizaci)
  private _completedPoints: GpsDataPoint[] = [];

  private getTalkerId(sentence: string): string | null {
    if (sentence.startsWith("$")) {
      return sentence.substring(1, 3);
    }
    return null;
  }

  /**
   * Zpracuje jednu NMEA větu.
   * @param sentence NMEA věta
   * @returns Kompletní GpsDataPoint, pokud byl exportován, jinak null.
   */
  public parse(sentence: string): Partial<GpsDataPoint> | null {
    // Kontrola platnosti a checksumu by měla být zde! (Pro zjednodušení vynecháno)
    const parts = sentence.split("*")[0].split(",");
    const talkerId = this.getTalkerId(sentence);
    const sentenceType = parts[0].substring(3);
    const timestamp = parts[1]; // Čas HHMMSS.SS

    if (!talkerId) return null;

    // --- 1. Zpracování času a export bodu ---

    // Pokud se časové razítko změnilo A máme už data v cache, exportujeme starý bod.
    // Tím zajistíme, že všechny RMC, GGA, GSV věty pro jedno časové razítko jsou spojeny.
    if (
      this._lastTimestamp !== null &&
      timestamp &&
      timestamp !== this._lastTimestamp
    ) {
      const exportedPoint = this._exportPoint();
      // Resetování cache pro nový časový slot
      this._dataCache = {};
      this._satelliteCache = {};
      this._gnssType = "Unknown";

      if (exportedPoint) {
        return exportedPoint;
      }
    }

    // Uložení nového/stejného časového razítka
    if (timestamp) {
      this._lastTimestamp = timestamp;
    }

    // --- 2. Aktualizace GNSS typu ---

    if (talkerId === "GP") {
      this._gnssType = this._gnssType === "Unknown" ? "GPS" : "Combined";
    } else if (talkerId === "GL") {
      this._gnssType = this._gnssType === "Unknown" ? "GLONASS" : "Combined";
    } else if (talkerId === "GN" || talkerId === "BD") {
      this._gnssType = "Combined";
    }

    // --- 3. Zpracování polohy a hlavních dat ---

    // RMC: Hlavní poloha, čas, rychlost, směr, magvar
    if (sentenceType === "RMC" && parts.length >= 10) {
      this._lastDate = parts[9] || this._lastDate; // Získej datum

      this._dataCache.time = createDateFromNmea(
        this._lastTimestamp,
        this._lastDate
      );

      // Konverze NMEA DDM.MMMM na desetinné stupně (DDD.DDDDDD) - KRITICKÁ OPRAVA!
      this._dataCache.latitude = convertNmeaCoordToDecimal(parts[3], parts[4]);
      this._dataCache.longitude = convertNmeaCoordToDecimal(parts[5], parts[6]);

      // Rychlost a směr
      this._dataCache.speedKnots = parseNumber(parts[7]);
      this._dataCache.courseDegrees = parseNumber(parts[8]);

      // Magnetická deklinace
      const magvarValue = parseNumber(parts[10]);
      if (magvarValue) {
        const magvarDirection = parts[11]; // E nebo W
        this._dataCache.magvar =
          magvarDirection === "W" ? -magvarValue : magvarValue;
      }
    }
    // GGA: Nadm. výška, HDOP, Fix Type
    else if (sentenceType === "GGA" && parts.length >= 10) {
      this._dataCache.time = createDateFromNmea(
        this._lastTimestamp,
        this._lastDate
      );

      // Některé přijímače posílají polohu i v GGA, použijeme ji, pokud ji nemáme z RMC/GNS
      if (this._dataCache.latitude === undefined) {
        this._dataCache.latitude = convertNmeaCoordToDecimal(
          parts[2],
          parts[3]
        );
        this._dataCache.longitude = convertNmeaCoordToDecimal(
          parts[4],
          parts[5]
        );
      }

      this._dataCache.fixType = parseNumber(parts[6]);
      this._dataCache.satellitesInUse = parseNumber(parts[7]);
      this._dataCache.hdop = parseNumber(parts[8]);
      this._dataCache.elevation = parseNumber(parts[9]);
      this._dataCache.geoidHeight = parseNumber(parts[11]);
    }
    // GSA: PDOP, HDOP, VDOP
    else if (sentenceType.endsWith("GSA") && parts.length >= 17) {
      this._dataCache.pdop = parseNumber(parts[15]);
      // HDOP a VDOP z GSA použijeme, jen pokud nemáme z GGA (GGA je obvykle přesnější pro DOP)
      this._dataCache.hdop = this._dataCache.hdop || parseNumber(parts[16]);
      this._dataCache.vdop = parseNumber(parts[17]);
      // Satelity v použití jsou pole 3 až 14
    }
    // GSV: Satelitní data (SNR, Azimuth, Elevation)
    else if (sentenceType.endsWith("GSV") && parts.length > 6) {
      // Přeskočíme hlavičku (0-6) a iterujeme po blocích (PRN, Elevace, Azimut, SNR)
      for (let i = 4; i < parts.length - 1; i += 4) {
        const prn = parseNumber(parts[i]);
        if (prn) {
          this._satelliteCache[prn] = {
            prn: prn,
            elevation: parseNumber(parts[i + 1]),
            azimuth: parseNumber(parts[i + 2]),
            snr: parseNumber(parts[i + 3]),
          };
        }
      }
    }

    return null; // Bod bude exportován až při nové časové značce
  }

  /**
   * Vytvoří GpsDataPoint z cache, pokud je platný, a resetuje cache.
   */
  private _exportPoint(): Partial<GpsDataPoint> | null {
    // Bod je platný, pokud má alespoň souřadnice a čas
    if (
      this._dataCache.latitude === null ||
      this._dataCache.longitude === null ||
      !this._dataCache.time
    ) {
      return null;
    }

    // Finalizace satelitních dat
    const satellites: SatelliteInfo[] = Object.values(this._satelliteCache).map(
      (sat) => ({
        prn: sat.prn!, // Musí existovat, jinak by nebyl v cache
        elevation: sat.elevation || 0,
        azimuth: sat.azimuth || 0,
        snr: sat.snr || 0,
      })
    );

    // Sestavení kompletního bodu
    const completedPoint: Partial<GpsDataPoint> = {
      ...(this._dataCache as GpsDataPoint), // Typ-konverze, protože víme, že klíčová pole existují
      satellites: satellites,
      gnssType: this._gnssType,
      isFiltered: false, // Bude nastaveno v GpxTrackGeneratoru
      // Zajistíme, že všechny numerické pole jsou správně nastaveny na null, pokud chybí
      elevation: this._dataCache.elevation,
      magvar: this._dataCache.magvar,
      speedKnots: this._dataCache.speedKnots,
      courseDegrees: this._dataCache.courseDegrees,
      fixType: this._dataCache.fixType,
      satellitesInUse: this._dataCache.satellitesInUse,
      hdop: this._dataCache.hdop,
      vdop: this._dataCache.vdop,
      pdop: this._dataCache.pdop,
      geoidHeight: this._dataCache.geoidHeight,
    };

    return completedPoint;
  }

  /**
   * Voláno na konci streamu pro export posledního bodu.
   */
  public flush(): Partial<GpsDataPoint> | null {
    return this._exportPoint();
  }
}
