import { Body, Controller, Delete, Get, Param, Post, Query } from '@nestjs/common';
import { UserCenterService } from './user-center.service';

@Controller('user-center')
export class UserCenterController {
  constructor(private readonly userCenterService: UserCenterService) {}

  @Get('favorites/models')
  async getFavoriteModels(@Query('userId') userId?: string) {
    const data = await this.userCenterService.getFavoriteModels(userId);
    return { success: true, data };
  }

  @Post('favorites/models')
  async addFavoriteModel(@Body() body: any) {
    const userId = body?.userId;
    const payload = body?.item ?? body;
    const data = await this.userCenterService.addFavoriteModel(payload, userId);
    return { success: true, data };
  }

  @Delete('favorites/models/:name')
  async removeFavoriteModel(@Param('name') name: string, @Query('userId') userId?: string) {
    const data = await this.userCenterService.removeFavoriteModel(name, userId);
    return { success: true, data };
  }

  @Get('favorites/data')
  async getFavoriteData(@Query('userId') userId?: string) {
    const data = await this.userCenterService.getFavoriteData(userId);
    return { success: true, data };
  }

  @Post('favorites/data')
  async addFavoriteData(@Body() body: any) {
    const userId = body?.userId;
    const payload = body?.item ?? body;
    const data = await this.userCenterService.addFavoriteData(payload, userId);
    return { success: true, data };
  }

  @Delete('favorites/data/:name')
  async removeFavoriteData(@Param('name') name: string, @Query('userId') userId?: string) {
    const data = await this.userCenterService.removeFavoriteData(name, userId);
    return { success: true, data };
  }

  @Get('simulation-results')
  async getSimulationResults(@Query('userId') userId?: string) {
    const data = await this.userCenterService.getSimulationResults(userId);
    return { success: true, data };
  }

  @Post('simulation-results')
  async addSimulationResult(@Body() body: any) {
    const userId = body?.userId;
    const payload = body?.item ?? body;
    const data = await this.userCenterService.addSimulationResult(payload, userId);
    return { success: true, data };
  }
}
