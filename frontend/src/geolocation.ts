const MAP_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN

export type ApproximateLocation = {
  longitude: number
  latitude: number
}

type ReverseGeocodeFeature = {
  properties?: {
    feature_type?: string
    full_address?: string
    name_preferred?: string
    name?: string
    bbox?: number[]
  }
}

type ReverseGeocodeResponse = {
  features?: ReverseGeocodeFeature[]
}

export type ReverseLocation = {
  label: string
  bounds?: [number, number, number, number]
}

export function requestCurrentLocation(decimalPlaces = 1): Promise<ApproximateLocation> {
  if (!navigator.geolocation) {
    return Promise.reject(new Error('Location access is not available in this browser.'))
  }

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        // Round coordinates before sending them for reverse geocoding.
        resolve({
          longitude: Number(position.coords.longitude.toFixed(decimalPlaces)),
          latitude: Number(position.coords.latitude.toFixed(decimalPlaces)),
        })
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          reject(new Error('Location access was denied. You can still search for any origin.'))
        } else if (error.code === error.TIMEOUT) {
          reject(new Error('The location request timed out. Please try again.'))
        } else {
          reject(new Error('Your location could not be determined. You can still search for any origin.'))
        }
      },
      { enableHighAccuracy: false, maximumAge: 5 * 60 * 1000, timeout: 15000 },
    )
  })
}

export async function reverseGeocode(
  location: ApproximateLocation,
  types: string,
  signal?: AbortSignal,
): Promise<ReverseLocation | null> {
  if (!MAP_TOKEN) return null

  const params = new URLSearchParams({
    longitude: String(location.longitude),
    latitude: String(location.latitude),
    types,
    permanent: 'false',
    access_token: MAP_TOKEN,
  })
  const response = await fetch(`https://api.mapbox.com/search/geocode/v6/reverse?${params}`, { signal })
  if (!response.ok) return null

  const result: ReverseGeocodeResponse = await response.json()
  const features = result.features ?? []
  const feature = types === 'country'
    ? features.find((candidate) => candidate.properties?.feature_type === 'country')
    : ['place', 'locality', 'region', 'country']
      .map((featureType) => features.find((candidate) => candidate.properties?.feature_type === featureType))
      .find(Boolean)
  const properties = feature?.properties
  const label = properties?.full_address || properties?.name_preferred || properties?.name
  if (!label) return null

  const bounds = properties?.bbox
  const hasValidBounds = bounds?.length === 4 &&
    bounds.every(Number.isFinite) &&
    bounds[0] <= bounds[2] &&
    bounds[1] <= bounds[3]

  return {
    label,
    ...(hasValidBounds ? { bounds: bounds as [number, number, number, number] } : {}),
  }
}
