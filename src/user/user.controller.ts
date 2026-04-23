import { Body, Controller, Delete, Get, Param, Post, Query, Req } from '@nestjs/common';
import type { Request } from 'express';
import { UserService } from './user.service';

@Controller('api/user')
export class UserController {
  constructor(private readonly userService: UserService) {}

  @Get('favorites/models')
  async getFavoriteModels(@Query('userId') userId?: string, @Req() req?: Request) {
    const data = await this.userService.getFavoriteModels(userId, req);
    return { success: true, data };
  }

  @Post('favorites/models')
  async addFavoriteModel(@Body() body: any, @Req() req?: Request) {
    const userId = body?.userId;
    const payload = body?.item ?? body;
    const data = await this.userService.addFavoriteModel(payload, userId, req);
    return { success: true, data };
  }

  @Delete('favorites/models/:name')
  async removeFavoriteModel(
    @Param('name') name: string,
    @Query('userId') userId?: string,
    @Req() req?: Request,
  ) {
    const data = await this.userService.removeFavoriteModel(name, userId, req);
    return { success: true, data };
  }

  @Get('favorites/data')
  async getFavoriteData(@Query('userId') userId?: string, @Req() req?: Request) {
    const data = await this.userService.getFavoriteData(userId, req);
    return { success: true, data };
  }

  @Post('favorites/data')
  async addFavoriteData(@Body() body: any, @Req() req?: Request) {
    const userId = body?.userId;
    const payload = body?.item ?? body;
    const data = await this.userService.addFavoriteData(payload, userId, req);
    return { success: true, data };
  }

  @Delete('favorites/data/:name')
  async removeFavoriteData(
    @Param('name') name: string,
    @Query('userId') userId?: string,
    @Req() req?: Request,
  ) {
    const data = await this.userService.removeFavoriteData(name, userId, req);
    return { success: true, data };
  }

  @Get('simulation-results')
  async getSimulationResults(@Query('userId') userId?: string, @Req() req?: Request) {
    const data = await this.userService.getSimulationResults(userId, req);
    return { success: true, data };
  }

  @Post('simulation-results')
  async addSimulationResult(@Body() body: any, @Req() req?: Request) {
    const userId = body?.userId;
    const payload = body?.item ?? body;
    const data = await this.userService.addSimulationResult(payload, userId, req);
    return { success: true, data };
  }
}
