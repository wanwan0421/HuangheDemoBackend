import { Injectable } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import { randomUUID } from 'crypto';
import { UserCenter, UserCenterDocument } from './schemas/user-center.schema';

@Injectable()
export class UserCenterService {
  private readonly defaultUserId = 'default';

  constructor(
    @InjectModel(UserCenter.name)
    private readonly userCenterModel: Model<UserCenterDocument>,
  ) {}

  private resolveUserId(userId?: string): string {
    const trimmed = (userId || '').trim();
    return trimmed || this.defaultUserId;
  }

  private getName(payload: any, fallback = 'unnamed'): string {
    if (typeof payload === 'string') {
      return payload;
    }

    if (payload && typeof payload === 'object') {
      const candidate =
        payload.name ?? payload.modelName ?? payload.title ?? payload.id ?? fallback;
      return String(candidate);
    }

    return fallback;
  }

  private normalizeObject(payload: any, fallbackName = 'unnamed'): Record<string, any> {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
      return payload;
    }

    return {
      name: this.getName(payload, fallbackName),
      value: payload,
    };
  }

  private async getOrCreate(userId?: string): Promise<UserCenterDocument> {
    const targetUserId = this.resolveUserId(userId);
    let doc = await this.userCenterModel.findOne({ userId: targetUserId }).exec();

    if (!doc) {
      doc = await this.userCenterModel.create({
        userId: targetUserId,
        favoriteModels: [],
        favoriteData: [],
        simulationResults: [],
      });
    }

    return doc;
  }

  async getFavoriteModels(userId?: string) {
    const doc = await this.getOrCreate(userId);
    return doc.favoriteModels || [];
  }

  async addFavoriteModel(payload: any, userId?: string) {
    const doc = await this.getOrCreate(userId);
    const next = this.normalizeObject(payload, 'model');
    const name = this.getName(next, 'model');

    const exists = (doc.favoriteModels || []).some((item) => this.getName(item) === name);
    if (!exists) {
      doc.favoriteModels.push({ ...next, name, createdAt: new Date().toISOString() });
      await doc.save();
    }

    return doc.favoriteModels;
  }

  async removeFavoriteModel(name: string, userId?: string) {
    const doc = await this.getOrCreate(userId);
    const target = decodeURIComponent(name);
    doc.favoriteModels = (doc.favoriteModels || []).filter(
      (item) => this.getName(item) !== target,
    );
    await doc.save();
    return doc.favoriteModels;
  }

  async getFavoriteData(userId?: string) {
    const doc = await this.getOrCreate(userId);
    return doc.favoriteData || [];
  }

  async addFavoriteData(payload: any, userId?: string) {
    const doc = await this.getOrCreate(userId);
    const next = this.normalizeObject(payload, 'data');
    const name = this.getName(next, 'data');

    const exists = (doc.favoriteData || []).some((item) => this.getName(item) === name);
    if (!exists) {
      doc.favoriteData.push({ ...next, name, createdAt: new Date().toISOString() });
      await doc.save();
    }

    return doc.favoriteData;
  }

  async removeFavoriteData(name: string, userId?: string) {
    const doc = await this.getOrCreate(userId);
    const target = decodeURIComponent(name);
    doc.favoriteData = (doc.favoriteData || []).filter(
      (item) => this.getName(item) !== target,
    );
    await doc.save();
    return doc.favoriteData;
  }

  async getSimulationResults(userId?: string) {
    const doc = await this.getOrCreate(userId);
    return doc.simulationResults || [];
  }

  async addSimulationResult(payload: any, userId?: string) {
    const doc = await this.getOrCreate(userId);
    const next = this.normalizeObject(payload, 'simulation-result');

    doc.simulationResults.push({
      ...next,
      id: next.id || randomUUID(),
      createdAt: next.createdAt || new Date().toISOString(),
    });

    await doc.save();
    return doc.simulationResults;
  }
}
