// --- Rozhraní pro NMEA data a GPX výstup ---

/** * Satelitní data z GSV věty
 * @param prn Číslo satelitu (PRN)
 * @param elevation Nadmořská výška (stupně)
 * @param azimuth Azimut (stupně)
 * @param snr Síla signálu (dB)
 */
export interface SatelliteInfo {
  prn: number;
  elevation: number | null;
  azimuth: number | null;
  snr: number | null;
}

/** * Data pro jeden GPS bod, shromážděná z různých NMEA vět (RMC, GGA, GSA, GSV)
 */
export interface GpsDataPoint {
  latitude: number; // Latituda
  longitude: number; // Longituda
  time: Date; // Čas z RMC
  elevation: number; // Nadmořská výška (ele)
  magvar: number; // Magnetická deklinace (magvar)
  speedKnots: number; // Rychlost v uzlech (pro převod na m/s)
  courseDegrees: number; // Směr pohybu (course)

  // Data z GGA, GSA, a DTM/VTG/GLL/apod. pro GPX (extensions/metadata)
  fixType: number | null; // Typ Fixu (1=No Fix, 2=2D, 3=3D, 4=GPS/GNSS, 5=Differential)
  satellitesInUse: number | null; // Počet satelitů (sat)
  hdop: number | null; // Horizontální přesnost
  vdop: number | null; // Vertikální přesnost
  pdop: number | null; // Pozicní přesnost
  geoidHeight: number | null; // Výška geoidu nad elipsoidem (geoidheight)

  // Rozšířené satelitní data
  satellites: SatelliteInfo[];
  gnssType: "GPS" | "GLONASS" | "Combined" | "Unknown";

  // Interní stav pro filtraci
  isFiltered: boolean;
}

/** * Parametry pro filtraci
 */
export interface FilterOptions {
  minTimeChangeMs?: number; // Minimální změna času (ms)
  minCourseChangeDeg?: number; // Minimální změna směru (stupně)
  minDistanceChangeMeters?: number; // Minimální skutečná vzdálenost (metry)
}

/** * Možnosti konverze
 */
export interface ConversionOptions {
  gnssFilter: "all" | "gps" | "glonass";
  filterOptions: FilterOptions;
}
