import { useEffect, useMemo, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { requestCurrentLocation, reverseGeocode, type ApproximateLocation } from './geolocation'

export type RiskName = 'Low' | 'Moderate' | 'High' | 'Severe' | 'No Travel'

export type RouteCheckpoint = {
  mile: number
  longitude: number
  latitude: number
  arrival_time: string
  elapsed_seconds: number
  risk: RiskName
  weather: { wind_mph: number; rain_in_per_hour: number; snow_in_per_hour: number }
  hazards: { wind: RiskName; rain: RiskName; snow: RiskName; load_adjustment: RiskName | null }
}

export type RouteResult = {
  id: string
  route_number: number
  rank: number
  strategy: string
  geometry: [number, number][]
  distance_miles: number
  duration_seconds: number
  estimated_arrival: string
  risk_summary: {
    severe_miles: number
    high_miles: number
    average_risk: number
    no_travel_miles: number
    eligible: boolean
  }
  checkpoints: RouteCheckpoint[]
}

export type AnalysisResult = {
  origin: { label: string; longitude: number; latitude: number }
  destination: { label: string; longitude: number; latitude: number }
  departure_time: string
  load_weight_lb: number
  checkpoint_interval_miles: number
  route_count: number
  required_route_count: number
  recommendation_id: string | null
  routes: RouteResult[]
  warnings: string[]
  weather_source: string
  routing_source: string
  generated_at: string
}

export type CorridorForecast = {
  forecast_time: string
  forecast_offset_hours: number
  weather_source: string
  routes: Record<string, Array<{
    mile: number
    longitude: number
    latitude: number
    risk: RiskName
    weather: { wind_mph: number; rain_in_per_hour: number; snow_in_per_hour: number }
  }>>
}

const MAP_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN

function emptyFeatureCollection() {
  return { type: 'FeatureCollection' as const, features: [] }
}

function riskColor(risk: RiskName) {
  switch (risk) {
    case 'Low': return '#37876b'
    case 'Moderate': return '#7d9f70'
    case 'High': return '#d6a241'
    case 'Severe': return '#d67b48'
    case 'No Travel': return '#c64b4b'
  }
}

type Props = {
  analysis: AnalysisResult | null
  selectedRouteId: string | null
  corridorForecast: CorridorForecast | null
  focusLocation: ApproximateLocation | null
}

export default function RouteMap({ analysis, selectedRouteId, corridorForecast, focusLocation }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const hasAnalysisRef = useRef(Boolean(analysis))
  const hasManualFocusRef = useRef(Boolean(focusLocation))
  const [mapReady, setMapReady] = useState(false)
  hasAnalysisRef.current = Boolean(analysis)
  hasManualFocusRef.current = Boolean(focusLocation)

  const routeFeatures = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: (analysis?.routes ?? []).map((route) => ({
      type: 'Feature' as const,
      properties: { routeId: route.id, isRecommended: route.id === analysis?.recommendation_id },
      geometry: { type: 'LineString' as const, coordinates: route.geometry },
    })),
  }), [analysis])

  const checkpointFeatures = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: (analysis?.routes ?? []).flatMap((route) => route.checkpoints.map((checkpoint, index) => {
      const forecastPoint = corridorForecast?.routes[route.id]?.[index]
      const risk = forecastPoint?.risk ?? checkpoint.risk
      return {
        type: 'Feature' as const,
        properties: {
          routeId: route.id,
          risk,
          color: riskColor(risk),
          mile: checkpoint.mile,
        },
        geometry: { type: 'Point' as const, coordinates: [checkpoint.longitude, checkpoint.latitude] },
      }
    })),
  }), [analysis, corridorForecast])

  useEffect(() => {
    if (!containerRef.current || !MAP_TOKEN) return
    const map = new mapboxgl.Map({
      container: containerRef.current,
      accessToken: MAP_TOKEN,
      style: 'mapbox://styles/mapbox/light-v11',
      center: [0, 20],
      zoom: 1.7,
      projection: 'mercator',
      attributionControl: true,
    })
    let isDisposed = false
    let reverseGeocodeController: AbortController | null = null
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
    map.once('load', () => {
      map.addSource('route-lines', { type: 'geojson', data: emptyFeatureCollection() })
      map.addSource('route-checkpoints', { type: 'geojson', data: emptyFeatureCollection() })
      map.addLayer({
        id: 'route-lines',
        type: 'line',
        source: 'route-lines',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': ['case', ['get', 'isRecommended'], '#1c8064', '#5685a0'],
          'line-width': ['case', ['==', ['get', 'routeId'], selectedRouteId ?? ''], 6, 4],
          'line-opacity': ['case', ['==', ['get', 'routeId'], selectedRouteId ?? ''], 0.95, 0.65],
        },
      })
      map.addLayer({
        id: 'route-checkpoints',
        type: 'circle',
        source: 'route-checkpoints',
        paint: {
          'circle-radius': ['case', ['==', ['get', 'routeId'], selectedRouteId ?? ''], 5, 3.5],
          'circle-color': ['get', 'color'],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
          'circle-opacity': 0.92,
        },
      })
      setMapReady(true)

      // Keep a late location result from overriding a route or chosen origin.
      void requestCurrentLocation().then(async (location) => {
        if (isDisposed || hasAnalysisRef.current || hasManualFocusRef.current) return
        reverseGeocodeController = new AbortController()
        try {
          const country = await reverseGeocode(location, 'country', reverseGeocodeController.signal)
          if (isDisposed || hasAnalysisRef.current || hasManualFocusRef.current) return
          if (country?.bounds) {
            const [west, south, east, north] = country.bounds
            map.fitBounds([[west, south], [east, north]], { padding: 48, maxZoom: 5.5, duration: 800 })
          } else {
            map.flyTo({ center: [location.longitude, location.latitude], zoom: 3.8, duration: 800 })
          }
        } catch {
          if (!isDisposed && !hasAnalysisRef.current && !hasManualFocusRef.current) {
            map.flyTo({ center: [location.longitude, location.latitude], zoom: 3.8, duration: 800 })
          }
        }
      }).catch(() => {
        // Keep the global map view when location access is denied or unavailable.
      })
    })
    mapRef.current = map
    return () => {
      isDisposed = true
      reverseGeocodeController?.abort()
      setMapReady(false)
      mapRef.current = null
      map.remove()
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady || !focusLocation || analysis) return
    map.flyTo({ center: [focusLocation.longitude, focusLocation.latitude], zoom: 5.5, duration: 800 })
  }, [focusLocation, analysis, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const lineSource = map.getSource('route-lines') as mapboxgl.GeoJSONSource | undefined
    const checkpointSource = map.getSource('route-checkpoints') as mapboxgl.GeoJSONSource | undefined
    lineSource?.setData(routeFeatures)
    checkpointSource?.setData(checkpointFeatures)
    if (analysis?.routes.length) {
      const bounds = new mapboxgl.LngLatBounds()
      analysis.routes.forEach((route) => route.geometry.forEach((coordinate) => bounds.extend(coordinate)))
      map.fitBounds(bounds, { padding: 70, maxZoom: 12, duration: 500 })
    }
  }, [analysis, routeFeatures, checkpointFeatures, mapReady])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    if (map.getLayer('route-lines')) {
      map.setPaintProperty('route-lines', 'line-width', ['case', ['==', ['get', 'routeId'], selectedRouteId ?? ''], 6, 4])
      map.setPaintProperty('route-lines', 'line-opacity', ['case', ['==', ['get', 'routeId'], selectedRouteId ?? ''], 0.95, 0.65])
    }
    if (map.getLayer('route-checkpoints')) {
      map.setPaintProperty('route-checkpoints', 'circle-radius', ['case', ['==', ['get', 'routeId'], selectedRouteId ?? ''], 5, 3.5])
    }
  }, [selectedRouteId, mapReady])

  if (MAP_TOKEN) return <div className="mapbox-container" ref={containerRef} aria-label="Route map" />

  return (
    <div className="map-empty" aria-label="Route map preview">
      <div className="map-contours" aria-hidden="true"><span /><span /><span /><span /></div>
      {analysis ? (
        <div className="map-setup-card"><strong>Map unavailable</strong><p>The route map could not be loaded right now.</p></div>
      ) : (
        <div className="empty-card"><div className="empty-icon">⌖</div><strong>Your route comparison will appear here</strong><p>Enter an origin, destination, departure time, and load weight to begin.</p></div>
      )}
      <div className="map-attribution">MAP PREVIEW · ROUTE ATTRIBUTION APPEARS WITH MAP DATA</div>
    </div>
  )
}
