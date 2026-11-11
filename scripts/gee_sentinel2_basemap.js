var bounds = [90.16394257543922, 23.130565172342898, 90.27306612742701, 23.265176626961278];
var region = ee.Geometry.Rectangle(bounds).buffer(200);

var start = '2024-11-01';
var end = '2026-04-30';

function maskClouds(image) {
  var scl = image.select('SCL');
  var valid = scl.gte(4)
    .and(scl.neq(8))
    .and(scl.neq(9))
    .and(scl.neq(10))
    .and(scl.neq(11));
  return image.updateMask(valid).divide(10000);
}

var collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(region)
  .filterDate(start, end)
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 35))
  .map(maskClouds);

var composite = collection
  .median()
  .select(['B4', 'B3', 'B2'], ['red', 'green', 'blue'])
  .clip(region);

var preview = composite.visualize({min: 0.02, max: 0.28, gamma: 1.1});
Map.centerObject(region, 12);
Map.addLayer(preview, {}, 'Sentinel-2 dry-season median');
Map.addLayer(region, {color: 'yellow'}, 'Export footprint');

Export.image.toDrive({
  image: composite,
  description: 'arial_khan_sentinel2_basemap',
  folder: 'riverguard_basemap',
  fileNamePrefix: 'sentinel2_basemap_raw',
  region: region,
  scale: 10,
  crs: 'EPSG:4326',
  maxPixels: 1e10,
  fileFormat: 'GeoTIFF'
});

print('Sentinel-2 scenes in collection:', collection.size());
print('Export footprint bounds:', region.bounds());
print('Run the Drive task, download the GeoTIFF, then run:');
print('  .venv/bin/python scripts/prepare_basemap.py /path/to/sentinel2_basemap_raw.tif');
