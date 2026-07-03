# remote-sensing-server

A small Python service for landcover and COG visualization.

## Configuration

The service reads landcover data locations from environment variables when set:

- `LANDCOVER_COG_DIR`: directory containing yearly COG files
- `LANDCOVER_STATISTICS_DIR`: directory containing landcover statistics CSV files

If these variables are not set, the service falls back to the current local development paths defined in `app/core/config.py`.

## Layout

- app/main.py: FastAPI app entry
- app/routers/landcover.py: landcover routes
- app/services/landcover_tile_service.py: tile rendering logic
- app/styles/landcover_colormap.py: landcover colormap definitions
- app/schemas/landcover.py: request/response models
