return {
	classes={
		[1]={
			ascendancies={
				[1]={
					background={
						height=1500,
						image="ClassesMartial Artist",
						section="AscendancyBackground",
						width=1500,
						x=11574.564583473,
						y=-10364.38737295
					},
					id="Martial Artist",
					internalId="Monk1",
					name="Martial Artist"
				},
				[2]={
					background={
						height=1500,
						image="ClassesInvoker",
						section="AscendancyBackground",
						width=1500,
						x=13476.509879863,
						y=-7731.4133488973
					},
					id="Invoker",
					internalId="Monk2",
					name="Invoker"
				},
				[3]={
					background={
						height=1500,
						image="ClassesAcolyte of Chayula",
						section="AscendancyBackground",
						width=1500,
						x=14789.467027034,
						y=-4760.5394620606
					},
					id="Acolyte of Chayula",
					internalId="Monk3",
					name="Acolyte of Chayula"
				}
			},
			background={
				active={
					height=2000,
					width=2000
				},
				bg={
					height=2000,
					width=2000
				},
				height=1500,
				image="ClassesMonk",
				section="AscendancyBackground",
				width=1500,
				x=0,
				y=0
			},
			["base_dex"]=11,
			["base_int"]=11,
			["base_str"]=7,
			integerId=10,
			name="Monk"
		}
	},
	nodes={
		[4]={
			connections={
				[1]={
					id=11578,
					orbit=0
				}
			},
			group=1069,
			icon="Art/2DArt/SkillIcons/passives/LightningDamagenode.dds",
			name="Shock Chance",
			orbit=0,
			orbitIndex=0,
			skill=4,
			stats={
				[1]="15% increased chance to Shock"
			},
			stringId="lightning14"
		},
		[52]={
			connections={
				[1]={
					id=39131,
					orbit=0
				}
			},
			flavourText="Tear my flesh and splinter my bones. You will never break my spirit.",
			group=194,
			icon="Art/2DArt/SkillIcons/passives/liferegentoenergyshield.dds",
			isKeystone=true,
			name="Zealot's Oath",
			orbit=0,
			orbitIndex=0,
			skill=52,
			stats={
				[1]="Excess Life Recovery from Regeneration is applied to Energy Shield",
				[2]="Energy Shield does not Recharge"
			},
			stringId="passive_keystone_zealots_oath"
		},
		[59]={
			ascendancyName="Lich",
			connections={
			},
			group=1215,
			icon="Art/2DArt/SkillIcons/passives/Lich/LichApplyAdditionalCurses.dds",
			isNotable=true,
			isSwitchable=true,
			name="Incessant Cacophony",
			nodeOverlay={
				alloc="LichFrameLargeAllocated",
				path="LichFrameLargeCanAllocate",
				unalloc="LichFrameLargeNormal"
			},
			options={
				["Abyssal Lich"]={
					ascendancyName="Abyssal Lich",
					nodeOverlay={
						alloc="Abyssal LichFrameSmallAllocated",
						path="Abyssal LichFrameSmallCanAllocate",
						unalloc="Abyssal LichFrameSmallNormal"
					}
				}
			},
			orbit=8,
			orbitIndex=50,
			skill=59,
			stats={
				[1]="Curses you inflict have infinite Duration",
				[2]="You can apply an additional Curse"
			},
			stringId="AscendancyWitch3Notable9"
		},
		[240]={
			activeEffectImage="Art/2DArt/UIImages/InGame/PassiveMastery/MasteryBackgroundGraphic/MasteryLightningPattern",
			connections={
				[1]={
					id=50498,
					orbit=0
				}
			},
			group=1219,
			icon="Art/2DArt/SkillIcons/passives/MasteryGroupLightning.dds",
			isOnlyImage=true,
			name="Lightning Mastery",
			orbit=0,
			orbitIndex=0,
			skill=240,
			stats={
			},
			stringId="mastery_lightning150"
		},
		[516]={
			connections={
				[1]={
					id=47157,
					orbit=4
				}
			},
			group=752,
			icon="Art/2DArt/SkillIcons/passives/projectilespeed.dds",
			name="Projectile Damage",
			orbit=7,
			orbitIndex=16,
			skill=516,
			stats={
				[1]="Projectiles deal 15% increased Damage with Hits against Enemies further than 6m"
			},
			stringId="projectiles32"
		},
		[722]={
			connections={
				[1]={
					id=3419,
					orbit=0
				},
				[2]={
					id=15775,
					orbit=0
				}
			},
			group=1479,
			icon="Art/2DArt/SkillIcons/passives/plusattribute.dds",
			isAttribute=true,
			name="Attribute",
			options={
				[1]={
					icon="Art/2DArt/SkillIcons/passives/plusstrength.dds",
					id=26297,
					name="Strength",
					stats={
						[1]="+5 to Strength"
					}
				},
				[2]={
					icon="Art/2DArt/SkillIcons/passives/plusdexterity.dds",
					id=14927,
					name="Dexterity",
					stats={
						[1]="+5 to Dexterity"
					}
				},
				[3]={
					icon="Art/2DArt/SkillIcons/passives/plusintelligence.dds",
					id=57022,
					name="Intelligence",
					stats={
						[1]="+5 to Intelligence"
					}
				}
			},
			orbit=0,
			orbitIndex=0,
			skill=722,
			stats={
				[1]="+5 to any Attribute"
			},
			stringId="dexterity46"
		},
		[1143]={
			connections={
				[1]={
					id=58170,
					orbit=0
				},
				[2]={
					id=50084,
					orbit=0
				}
			},
			group=680,
			icon="Art/2DArt/SkillIcons/passives/SpellMultiplyer2.dds",
			isSwitchable=true,
			name="Spell Critical Damage",
			options={
				Druid={
					icon="Art/2DArt/SkillIcons/passives/lifepercentage.dds",
					id=57726,
					name="Life Regeneration",
					stats={
						[1]="Regenerate 0.2% of maximum Life per second"
					}
				}
			},
			orbit=2,
			orbitIndex=5,
			skill=1143,
			stats={
				[1]="15% increased Critical Spell Damage Bonus"
			},
			stringId="spell_criticals7"
		},
		[2491]={
			connections={
				[1]={
					id=28175,
					orbit=0
				}
			},
			group=412,
			icon="Art/2DArt/SkillIcons/passives/MasteryBlank.dds",
			isJewelSocket=true,
			name="Jewel Socket",
			orbit=1,
			orbitIndex=10,
			skill=2491,
			stats={
			},
			stringId="jewel_slot1974"
		},
		[2516]={
			ascendancyName="Lich",
			connections={
			},
			group=1275,
			icon="Art/2DArt/SkillIcons/passives/Lich/LichSpellsConsumePowerCharges.dds",
			isNotable=true,
			isSwitchable=true,
			name="Price of Power",
			nodeOverlay={
				alloc="LichFrameLargeAllocated",
				path="LichFrameLargeCanAllocate",
				unalloc="LichFrameLargeNormal"
			},
			options={
				["Abyssal Lich"]={
					ascendancyName="Abyssal Lich",
					icon="Art/2DArt/SkillIcons/passives/Lich/AbyssalLichAbyssalApparition.dds",
					id=11705,
					name="Steward of Kulemak",
					nodeOverlay={
						alloc="Abyssal LichFrameSmallAllocated",
						path="Abyssal LichFrameSmallCanAllocate",
						unalloc="Abyssal LichFrameSmallNormal"
					},
					stats={
						[1]="Damaging Spells consume a Power Charge if able to trigger Abyssal Apparition"
					}
				}
			},
			orbit=0,
			orbitIndex=0,
			skill=2516,
			stats={
				[1]="Spells consume a Power Charge if able to deal 40% more Damage"
			},
			stringId="AscendancyWitch3Notable7"
		},
		[3281]={
			activeEffectImage="Art/2DArt/UIImages/InGame/PassiveMastery/MasteryBackgroundGraphic/MasteryAttributesPattern",
			connectionArt="CharacterPlanned",
			connections={
				[1]={
					id=35720,
					orbit=0
				}
			},
			group=725,
			icon="Art/2DArt/SkillIcons/passives/plusstrength.dds",
			isNotable=true,
			name="Powerful Casting",
			nodeOverlay={
				alloc="art/textures/interface/2d/2dart/uiimages/ingame/oraclepassiveskillscreennotableframeactive.dds",
				path="art/textures/interface/2d/2dart/uiimages/ingame/oraclepassiveskillscreennotableframecanallocate.dds",
				unalloc="art/textures/interface/2d/2dart/uiimages/ingame/oraclepassiveskillscreennotableframenormal.dds"
			},
			orbit=0,
			orbitIndex=0,
			skill=3281,
			stats={
				[1]="2% increased Spell Damage per 10 Strength"
			},
			stringId="oracle_strength_spell4",
			unlockConstraint={
				ascendancy="Oracle",
				nodes={
					[1]=5571
				}
			}
		},
		[9994]={
			ascendancyName="Invoker",
			connections={
				[1]={
					id=23415,
					orbit=0
				},
				[2]={
					id=44357,
					orbit=0
				},
				[3]={
					id=13065,
					orbit=0
				},
				[4]={
					id=27686,
					orbit=0
				},
				[5]={
					id=25434,
					orbit=2147483647
				},
				[6]={
					id=17268,
					orbit=0
				}
			},
			group=1554,
			icon="Art/2DArt/SkillIcons/passives/damage.dds",
			isAscendancyStart=true,
			name="Invoker",
			nodeOverlay={
				alloc="InvokerFrameSmallAllocated",
				path="InvokerFrameSmallCanAllocate",
				unalloc="InvokerFrameSmallNormal"
			},
			orbit=9,
			orbitIndex=24,
			skill=9994,
			stats={
			},
			stringId="AscendancyMonk2Start"
		},
		[11335]={
			ascendancyName="Oracle",
			connections={
				[1]={
					id=5571,
					orbit=6
				}
			},
			group=4,
			icon="Art/2DArt/SkillIcons/passives/Oracle/OracleNode.dds",
			name="Passive Point",
			nodeOverlay={
				alloc="OracleFrameSmallAllocated",
				path="OracleFrameSmallCanAllocate",
				unalloc="OracleFrameSmallNormal"
			},
			orbit=0,
			orbitIndex=0,
			skill=11335,
			stats={
				[1]="Grants 1 Passive Skill Point"
			},
			stringId="AscendancyDruid1Small1"
		},
		[14226]={
			connections={
			},
			flavourText="You circle the black scorpion with enmity, daring it time and again.",
			group=1447,
			icon="Art/2DArt/SkillIcons/passives/DancewithDeathKeystone.dds",
			isKeystone=true,
			name="Dance with Death",
			orbit=0,
			orbitIndex=0,
			skill=14226,
			stats={
				[1]="25% more Skill Speed while Off Hand is empty and you have",
				[2]="a One-Handed Martial Weapon equipped in your Main Hand"
			},
			stringId="passive_keystone_dance_with_death"
		},
		[18684]={
			connections={
			},
			flavourText="\"In my dreams I see a great warrior, his skin scorched black, his fists aflame.\"",
			group=137,
			icon="Art/2DArt/SkillIcons/passives/KeystoneAvatarOfFire.dds",
			isKeystone=true,
			name="Avatar of Fire",
			orbit=0,
			orbitIndex=0,
			skill=18684,
			stats={
				[1]="75% of Damage Converted to Fire Damage",
				[2]="Deal no Non-Fire Damage"
			},
			stringId="passive_keystone_avatar_of_fire"
		}
	},
}
