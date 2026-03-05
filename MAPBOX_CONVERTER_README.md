# Mapbox 地理数据转换服务

## 功能说明

该服务支持将用户上传的地理数据文件（Shapefile、GeoTIFF等）转换为 Mapbox 可显示的格式。

## 支持的格式

### 输入格式
- **矢量数据**: Shapefile (.shp), GeoJSON (.geojson, .json), KML (.kml)
- **栅格数据**: GeoTIFF (.tif, .tiff)

### 输出格式
- **矢量数据**: GeoJSON (EPSG:4326)
- **栅格数据**: 边界 GeoJSON + 元数据 + 统计信息

## API 接口

### 1. 上传并转换文件
```http
POST /api/data/upload-and-convert
Content-Type: multipart/form-data

参数:
- file: 地理数据文件（FormData）
- saveConverted: 是否保存转换后的文件 (可选, 'true' 或 'false')

响应示例（矢量数据）:
{
  "success": true,
  "message": "文件上传并转换成功",
  "originalFile": {
    "fileName": "example.shp",
    "fileSize": 123456,
    "filePath": "/path/to/example.shp"
  },
  "conversion": {
    "success": true,
    "type": "vector",
    "format": "geojson",
    "data": { ... GeoJSON 数据 ... },
    "bounds": [minX, minY, maxX, maxY],
    "crs": "EPSG:4326",
    "feature_count": 100,
    "geometry_type": ["Polygon"]
  }
}

响应示例（栅格数据）:
{
  "success": true,
  "message": "文件上传并转换成功",
  "originalFile": { ... },
  "conversion": {
    "success": true,
    "type": "raster",
    "format": "geotiff",
    "bounds_geojson": {
      "type": "Feature",
      "geometry": { ... 边界几何 ... },
      "properties": { ... }
    },
    "metadata": {
      "width": 1024,
      "height": 768,
      "count": 1,
      "bounds": [minX, minY, maxX, maxY]
    },
    "statistics": {
      "min": 0,
      "max": 255,
      "mean": 127.5,
      "std": 50.2
    }
  }
}
```

### 2. 转换已上传的文件
```http
POST /api/data/convert
Content-Type: application/json

Body:
{
  "filePath": "/absolute/path/to/file.shp",
  "saveConverted": false  // 可选
}

响应: 同上 conversion 部分
```

### 3. 批量转换
```http
POST /api/data/convert-batch
Content-Type: application/json

Body:
{
  "filePaths": [
    "/path/to/file1.shp",
    "/path/to/file2.tif"
  ],
  "saveConverted": false  // 可选
}

响应:
{
  "success": true,
  "message": "批量转换完成",
  "total": 2,
  "results": [
    {
      "filePath": "/path/to/file1.shp",
      "success": true,
      ...
    },
    ...
  ]
}
```

## 前端集成示例

### 使用 Mapbox GL JS 显示转换后的数据

#### 矢量数据 (GeoJSON)
```javascript
// 1. 上传并转换
const formData = new FormData();
formData.append('file', file);

const response = await fetch('/api/data/upload-and-convert', {
  method: 'POST',
  body: formData
});

const result = await response.json();

// 2. 在 Mapbox 中显示
if (result.conversion.type === 'vector') {
  map.addSource('uploaded-data', {
    type: 'geojson',
    data: result.conversion.data
  });

  map.addLayer({
    id: 'uploaded-layer',
    type: 'fill',  // 或 'line', 'circle' 根据几何类型
    source: 'uploaded-data',
    paint: {
      'fill-color': '#088',
      'fill-opacity': 0.5
    }
  });

  // 缩放到数据范围
  const bounds = result.conversion.bounds;
  map.fitBounds([
    [bounds[0], bounds[1]],
    [bounds[2], bounds[3]]
  ]);
}
```

#### 栅格数据
```javascript
if (result.conversion.type === 'raster') {
  // 显示边界
  map.addSource('raster-bounds', {
    type: 'geojson',
    data: result.conversion.bounds_geojson
  });

  map.addLayer({
    id: 'raster-bounds-layer',
    type: 'line',
    source: 'raster-bounds',
    paint: {
      'line-color': '#ff0000',
      'line-width': 2
    }
  });

  // 如果需要显示栅格图像，可以使用 Mapbox Raster Tiles 或其他瓦片服务
  // 注意：直接显示大型 GeoTIFF 需要额外的瓦片切割服务
}
```

## Python 依赖

确保已安装以下 Python 包：
- geopandas
- rasterio
- shapely
- numpy
- Pillow (PIL)
- scipy (可选，用于图像缩放)

安装命令：
```bash
pip install geopandas rasterio shapely numpy Pillow scipy
```

## 注意事项

1. **坐标系转换**: 所有矢量数据会自动转换为 WGS84 (EPSG:4326) 以兼容 Mapbox
2. **文件大小限制**: 默认最大 500MB，可在代码中调整
3. **栅格数据**: 目前返回边界和元数据，如需显示图像内容需要额外的瓦片切割服务
4. **Shapefile**: 上传时需要包含所有相关文件 (.shp, .shx, .dbf 等)，可以打包为 .zip 上传

## 性能优化建议

1. **大文件处理**: 对于超大文件，建议使用流式处理或后台任务队列
2. **缓存**: 可以缓存转换结果避免重复转换
3. **CDN**: 转换后的 GeoJSON 可以存储到 CDN 加速访问
