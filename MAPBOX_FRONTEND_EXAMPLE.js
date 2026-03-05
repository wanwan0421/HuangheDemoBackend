// Mapbox 地理数据转换前端集成示例

// ============================================
// 1. 上传并转换地理数据文件
// ============================================

/**
 * 上传并转换地理数据文件为 Mapbox 可用格式
 * @param {File} file - 地理数据文件（.shp, .geojson, .tif 等）
 * @param {boolean} saveConverted - 是否在服务器保存转换后的文件
 * @returns {Promise<Object>} 转换结果
 */
async function uploadAndConvertGeoData(file, saveConverted = false) {
  const formData = new FormData();
  formData.append('file', file);
  
  const url = `/api/data/upload-and-convert?saveConverted=${saveConverted}`;
  
  try {
    const response = await fetch(url, {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      throw new Error(`上传失败: ${response.statusText}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error('上传并转换失败:', error);
    throw error;
  }
}

// ============================================
// 2. 在 Mapbox 中显示矢量数据 (GeoJSON)
// ============================================

/**
 * 在 Mapbox 地图上显示矢量数据
 * @param {mapboxgl.Map} map - Mapbox 地图实例
 * @param {Object} conversionResult - 转换结果对象
 * @param {string} sourceId - 数据源 ID
 * @param {string} layerId - 图层 ID
 */
function displayVectorDataOnMapbox(map, conversionResult, sourceId = 'uploaded-vector', layerId = 'uploaded-vector-layer') {
  if (conversionResult.type !== 'vector') {
    console.error('数据类型不是矢量数据');
    return;
  }
  
  // 添加数据源
  map.addSource(sourceId, {
    type: 'geojson',
    data: conversionResult.data
  });
  
  // 根据几何类型添加图层
  const geometryType = conversionResult.geometry_type[0];
  let layerConfig;
  
  if (geometryType === 'Polygon' || geometryType === 'MultiPolygon') {
    // 面图层
    layerConfig = {
      id: layerId,
      type: 'fill',
      source: sourceId,
      paint: {
        'fill-color': '#088',
        'fill-opacity': 0.5,
        'fill-outline-color': '#000'
      }
    };
  } else if (geometryType === 'LineString' || geometryType === 'MultiLineString') {
    // 线图层
    layerConfig = {
      id: layerId,
      type: 'line',
      source: sourceId,
      paint: {
        'line-color': '#088',
        'line-width': 2
      }
    };
  } else if (geometryType === 'Point' || geometryType === 'MultiPoint') {
    // 点图层
    layerConfig = {
      id: layerId,
      type: 'circle',
      source: sourceId,
      paint: {
        'circle-radius': 6,
        'circle-color': '#088',
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff'
      }
    };
  }
  
  if (layerConfig) {
    map.addLayer(layerConfig);
  }
  
  // 缩放到数据范围
  const bounds = conversionResult.bounds;
  map.fitBounds([
    [bounds[0], bounds[1]],
    [bounds[2], bounds[3]]
  ], {
    padding: 50,
    maxZoom: 15
  });
}

// ============================================
// 3. 在 Mapbox 中显示栅格数据边界
// ============================================

/**
 * 在 Mapbox 地图上显示栅格数据边界
 * @param {mapboxgl.Map} map - Mapbox 地图实例
 * @param {Object} conversionResult - 转换结果对象
 * @param {string} sourceId - 数据源 ID
 * @param {string} layerId - 图层 ID
 */
function displayRasterBoundsOnMapbox(map, conversionResult, sourceId = 'raster-bounds', layerId = 'raster-bounds-layer') {
  if (conversionResult.type !== 'raster') {
    console.error('数据类型不是栅格数据');
    return;
  }
  
  // 添加边界数据源
  map.addSource(sourceId, {
    type: 'geojson',
    data: conversionResult.bounds_geojson
  });
  
  // 添加边界线图层
  map.addLayer({
    id: layerId,
    type: 'line',
    source: sourceId,
    paint: {
      'line-color': '#ff0000',
      'line-width': 3,
      'line-dasharray': [2, 1]
    }
  });
  
  // 添加半透明填充
  map.addLayer({
    id: `${layerId}-fill`,
    type: 'fill',
    source: sourceId,
    paint: {
      'fill-color': '#ff0000',
      'fill-opacity': 0.1
    }
  });
  
  // 缩放到栅格范围
  const bounds = conversionResult.metadata.bounds;
  map.fitBounds([
    [bounds[0], bounds[1]],
    [bounds[2], bounds[3]]
  ], {
    padding: 50
  });
  
  // 显示栅格元数据
  console.log('栅格元数据:', conversionResult.metadata);
  console.log('栅格统计:', conversionResult.statistics);
}

// ============================================
// 4. 完整示例：文件上传并在地图上显示
// ============================================

/**
 * 处理文件上传并在 Mapbox 地图上显示
 * @param {File} file - 上传的地理数据文件
 * @param {mapboxgl.Map} map - Mapbox 地图实例
 */
async function handleGeoFileUpload(file, map) {
  try {
    // 显示加载状态
    console.log('正在上传和转换文件...');
    
    // 上传并转换
    const result = await uploadAndConvertGeoData(file);
    
    if (!result.success) {
      throw new Error(result.message || '转换失败');
    }
    
    console.log('转换成功:', result);
    
    const conversion = result.conversion;
    
    // 根据数据类型显示
    if (conversion.type === 'vector') {
      displayVectorDataOnMapbox(map, conversion);
      console.log(`已显示矢量数据: ${conversion.feature_count} 个要素`);
    } else if (conversion.type === 'raster') {
      displayRasterBoundsOnMapbox(map, conversion);
      console.log('已显示栅格数据边界');
    }
    
    return result;
  } catch (error) {
    console.error('处理地理数据文件失败:', error);
    alert(`处理失败: ${error.message}`);
    throw error;
  }
}

// ============================================
// 5. React 组件示例
// ============================================

/*
import React, { useRef, useState } from 'react';
import mapboxgl from 'mapbox-gl';

function GeoDataUploader({ map }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const fileInputRef = useRef(null);
  
  const handleFileChange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    setLoading(true);
    try {
      const uploadResult = await handleGeoFileUpload(file, map);
      setResult(uploadResult);
    } catch (error) {
      console.error('上传失败:', error);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".shp,.geojson,.json,.tif,.tiff,.kml"
        onChange={handleFileChange}
        disabled={loading}
      />
      {loading && <p>正在处理...</p>}
      {result && (
        <div>
          <p>转换成功！</p>
          <pre>{JSON.stringify(result.conversion, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
*/

// ============================================
// 6. Vue 组件示例
// ============================================

/*
<template>
  <div>
    <input
      type="file"
      accept=".shp,.geojson,.json,.tif,.tiff,.kml"
      @change="handleFileChange"
      :disabled="loading"
    />
    <div v-if="loading">正在处理...</div>
    <div v-if="result">
      <p>转换成功！</p>
      <pre>{{ JSON.stringify(result.conversion, null, 2) }}</pre>
    </div>
  </div>
</template>

<script>
export default {
  props: ['map'],
  data() {
    return {
      loading: false,
      result: null
    };
  },
  methods: {
    async handleFileChange(event) {
      const file = event.target.files[0];
      if (!file) return;
      
      this.loading = true;
      try {
        this.result = await handleGeoFileUpload(file, this.map);
      } catch (error) {
        console.error('上传失败:', error);
      } finally {
        this.loading = false;
      }
    }
  }
};
</script>
*/

// ============================================
// 导出函数
// ============================================

export {
  uploadAndConvertGeoData,
  displayVectorDataOnMapbox,
  displayRasterBoundsOnMapbox,
  handleGeoFileUpload
};
