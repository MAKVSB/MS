// --- Pomocné funkce pro GPX a filtraci ---

import type { ConversionOptions, GpsDataPoint } from "./interfaces";

/** Převod uzlů na metry za sekundu (m/s) */
export const knotsToMps = (knots: number) => knots * 0.514444;

/** Výpočet vzdálenosti mezi dvěma body (Haversine formula) */
export const haversineDistance = (
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number => {
  // ... implementace Haversine vzorce ...
  // (Pro zjednodušení to zanecháme jako zástupný kód)
  const R = 6371e3; // Poloměr Země v metrech
  const toRad = (d: number) => (d * Math.PI) / 180;

  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
};

/** Normalizace úhlu (směru) mezi 0 a 360 stupni */
export const normalizeAngle = (angle: number) => ((angle % 360) + 360) % 360;

/** Výpočet rozdílu úhlů (nejkratší cesta) */
export const angleDifference = (angle1: number, angle2: number): number => {
  const diff = Math.abs(normalizeAngle(angle1) - normalizeAngle(angle2));
  return Math.min(diff, 360 - diff);
};

export class GpxTrackGenerator {
  private trackPoints: GpsDataPoint[] = [];

  /**
   * Přidá datový bod k zpracování.
   */
  public addPoint(point: GpsDataPoint) {
    this.trackPoints.push(point);
  }

  /**
   * Vyfiltruje body na základě zadaných kritérií a GNSS filtru.
   */
  private filterPoints(options: ConversionOptions): Partial<GpsDataPoint>[] {
    let filtered: GpsDataPoint[] = [];
    let lastExportedPoint: GpsDataPoint | null = null;

    // 1. Filtr dle GNSS
    let gnssFiltered = this.trackPoints.filter((p) => {
      if (options.gnssFilter === "all") return true;
      if (
        options.gnssFilter === "gps" &&
        (p.gnssType === "GPS" || p.gnssType === "Combined")
      )
        return true;
      if (
        options.gnssFilter === "glonass" &&
        (p.gnssType === "GLONASS" || p.gnssType === "Combined")
      )
        return true;
      return false;
    });

    // 2. Filtrace podle ostatních kritérií (min. čas, směr, vzdálenost)
    for (const current of gnssFiltered) {
      if (!lastExportedPoint) {
        // Vždy zahrneme první platný bod
        filtered.push(current);
        lastExportedPoint = current;
        continue;
      }

      let include = false;

      // A) Minimální změna času
      if (
        options.filterOptions.minTimeChangeMs &&
        current.time.getTime() - lastExportedPoint.time.getTime() >=
          options.filterOptions.minTimeChangeMs
      ) {
        include = true;
      }

      // B) Minimální změna směru
      if (
        options.filterOptions.minCourseChangeDeg &&
        current.courseDegrees !== null &&
        lastExportedPoint.courseDegrees !== null &&
        angleDifference(
          current.courseDegrees,
          lastExportedPoint.courseDegrees
        ) >= options.filterOptions.minCourseChangeDeg
      ) {
        include = true;
      }

      // C) Minimální skutečná vzdálenost
      if (
        options.filterOptions.minDistanceChangeMeters &&
        current.latitude !== null &&
        current.longitude !== null &&
        lastExportedPoint.latitude !== null &&
        lastExportedPoint.longitude !== null &&
        haversineDistance(
          current.latitude,
          current.longitude,
          lastExportedPoint.latitude,
          lastExportedPoint.longitude
        ) >= options.filterOptions.minDistanceChangeMeters
      ) {
        include = true;
      }

      if (include) {
        filtered.push(current);
        lastExportedPoint = current;
      }
    }

    return filtered;
  }

  /**
   * Generuje GPX XML z filtrovaných bodů.
   * @param options Možnosti konverze.
   * @returns Řetězec s GPX XML.
   */
  public generateGpx(options: ConversionOptions): string {
    const filteredPoints = this.filterPoints(options);

    if (filteredPoints.length === 0) {
      return "<gpx></gpx>";
    }

    const HEADER = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="NMEA-to-GPX Converter" 
    xmlns="http://www.topografix.com/GPX/1/1" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd 
                        http://www.krasny.cz/nmea http://www.krasny.cz/nmea/nmea-extension.xsd"
    xmlns:nmea="http://www.krasny.cz/nmea">
<trk>
    <name>NMEA Tracklog (${new Date().toISOString()})</name>
    <trkseg>`;

    const FOOTER = `</trkseg>
</trk>
</gpx>`;

    const trackPointsXml = filteredPoints
      .map((p) => {
        // Získání času ve formátu ISO 8601 (nutné pro GPX)
        const timeIso = p.time!.toISOString();
        const speedMps = p.speedKnots ? knotsToMps(p.speedKnots) : null;

        // Formátování rozšířených dat (Extensions)
        let extensions = "";
        if (
          p.fixType ||
          p.satellitesInUse ||
          p.hdop ||
          p.vdop ||
          p.pdop ||
          p.geoidHeight ||
          speedMps !== null ||
          p.courseDegrees ||
          p.magvar ||
          (p.satellites && p.satellites.length > 0)
        ) {
          extensions += `<extensions>\n`;

          // NMEA/GPS standardní rozšíření
          if (p.fixType)
            extensions += `    <gpxx:fix>${p.fixType}</gpxx:fix>\n`; // Alternativně GPXX rozšíření
          if (p.satellitesInUse)
            extensions += `    <sat>${p.satellitesInUse}</sat>\n`;
          if (p.hdop) extensions += `    <hdop>${p.hdop.toFixed(2)}</hdop>\n`;
          if (p.vdop) extensions += `    <vdop>${p.vdop.toFixed(2)}</vdop>\n`;
          if (p.pdop) extensions += `    <pdop>${p.pdop.toFixed(2)}</pdop>\n`;
          if (p.geoidHeight)
            extensions += `    <geoidheight>${p.geoidHeight.toFixed(
              2
            )}</geoidheight>\n`;
          if (p.magvar)
            extensions += `    <magvar>${p.magvar.toFixed(2)}</magvar>\n`;

          // Vlastní NMEA rozšíření (rychlost, směr)
          if (speedMps)
            extensions += `    <nmea:speed>${speedMps.toFixed(
              2
            )}</nmea:speed>\n`; // m/s
          if (p.courseDegrees)
            extensions += `    <nmea:course>${p.courseDegrees.toFixed(
              2
            )}</nmea:course>\n`;

          // Data satelitů
          if (p.satellites && p.satellites.length > 0) {
            extensions += `    <nmea:satellites gnssType="${p.gnssType}">\n`;
            for (const sat of p.satellites) {
              extensions += `        <nmea:sat prn="${sat.prn}" ele="${sat.elevation}" azi="${sat.azimuth}" snr="${sat.snr}" />\n`;
            }
            extensions += `    </nmea:satellites>\n`;
          }

          extensions += `</extensions>`;
        }

        if (p.latitude && p.longitude) {
          // Sestavení <trkpt>
          return `
                <trkpt lat="${p.latitude.toFixed(
                  6
                )}" lon="${p.longitude.toFixed(6)}">
                    ${p.elevation ? `<ele>${p.elevation.toFixed(2)}</ele>` : ""}
                    <time>${timeIso}</time>
                    ${extensions}
                </trkpt>`;
        } else {
          return ``;
        }
      })
      .join("");

    return `${HEADER}${trackPointsXml}${FOOTER}`;
  }
}
